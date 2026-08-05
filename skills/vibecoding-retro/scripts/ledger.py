#!/usr/bin/env python3
"""vibecoding-retro 档案读写。仅标准库,零依赖。输出 JSON 到 stdout。

档案目录:~/.claude/vibecoding-retro/(可用 --dir 或环境变量 VIBECODING_RETRO_HOME 覆盖)
  sessions.jsonl        每次复盘的指标记录(append-only)
  reports/              每次复盘的报告全文,周报的素材来源
  notes.json            给过的建议(纯追加日志,没有状态机)
  session-index.jsonl   SessionEnd 钩子登记的会话索引

**这里刻意没有状态机。** 早期版本有一套"缺口台账"(观察→确认3次→结构性→连续5次未现→毕业),
删掉的原因:它要积累三五次会话才产出第一个结论,而这个工具的承诺是**每一段对话都有用**。
现在的原则——单次会话就能给出的东西才是主体,跨会话只做两件轻的事:报告归档、复发统计。

所有写操作:先序列化校验,再写临时文件,os.replace 原子替换——写坏档案是最严重的 bug。
"""
import argparse
import json
import os
import re
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASELINE_MIN_RECORDS = 10     # 少于这个数不出基线:没有分母就没有"超标"
COMPARE_FLAG_RATIO = 1.5      # 达到个人中位数的几倍才值得去查,低于此是正常波动
EFFECT_MIN_PER_SIDE = 3       # 前后对比每侧至少几条才敢说"看得出变化"

SCALES = ("small", "medium", "large")
# 旧记录用 S/M/L,读的时候归一化。规模只用于同类比较,**不出现在报告里**
LEGACY_SCALE = {"S": "small", "M": "medium", "L": "large"}

DEFAULT_NOTES = {"suggestions": []}


def default_dir():
    env = os.environ.get("VIBECODING_RETRO_HOME")
    return Path(env) if env else Path.home() / ".claude" / "vibecoding-retro"


def emit(obj, code=0):
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return code


def today():
    return date.today().isoformat()


def slugify(text, limit=32):
    """项目名/任务名 → 安全的文件名片段。"""
    if not text:
        return "unknown"
    keep = [c if (c.isalnum() or c in "-_") else "-" for c in str(text)]
    slug = re.sub(r"-+", "-", "".join(keep)).strip("-").lower()
    return (slug[:limit] or "unknown")


def scale_of(record):
    """取记录的任务规模,兼容旧记录的 complexity: S/M/L。"""
    s = record.get("scale")
    if s in SCALES:
        return s
    return LEGACY_SCALE.get(record.get("complexity"))


class Ledger:
    def __init__(self, base_dir):
        self.base = Path(base_dir)
        self.notes_path = self.base / "notes.json"
        self.sessions_path = self.base / "sessions.jsonl"
        self.reports_dir = self.base / "reports"

    def archive_report(self, src, record):
        """把报告全文复制进 reports/,返回相对档案目录的路径。"""
        src = Path(src)
        if not src.is_file():
            raise ValueError("报告文件不存在: %s" % src)
        content = src.read_text(encoding="utf-8")
        if not content.strip():
            raise ValueError("报告文件为空: %s" % src)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        project = record.get("project") or record.get("task_summary")
        sid = (record.get("session_id") or "")[:8]
        stem = "%s-%s" % (record.get("date") or today(), slugify(project))
        if sid:
            stem += "-" + sid
        dest = self.reports_dir / (stem + ".md")
        n = 2
        while dest.exists():  # 同一天同一会话复盘多段:加序号,不覆盖
            dest = self.reports_dir / ("%s-%d.md" % (stem, n))
            n += 1
        dest.write_text(content, encoding="utf-8")
        return "reports/" + dest.name

    def coverage(self, cutoff, records):
        """这段时间有多少段会话发生过、其中多少段真的复盘了。

        素材来自 SessionEnd 钩子写的 session-index.jsonl(只登记会话存在,不做分析)。
        钩子没装时返回 available:false——不要因此假装覆盖率是 100%。
        """
        index = self.base / "session-index.jsonl"
        if not index.is_file():
            return {"available": False, "reason": "SessionEnd 钩子未安装或本周无记录"}
        seen = {}
        try:
            with index.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    sid = rec.get("session_id")
                    if not sid or (rec.get("ts") or "")[:10] < cutoff:
                        continue
                    seen[sid] = rec.get("project")
        except OSError:
            return {"available": False, "reason": "session-index.jsonl 读取失败"}
        retroed = {r.get("session_id") for r in records if r.get("session_id")}
        missed = [
            {"session_id": sid, "project": proj}
            for sid, proj in seen.items()
            if sid not in retroed
        ]
        return {
            "available": True,
            "sessions_seen": len(seen),
            "sessions_retroed": len(seen) - len(missed),
            "not_retroed": missed,
        }

    def load_notes(self):
        if not self.notes_path.exists():
            return json.loads(json.dumps(DEFAULT_NOTES))
        with self.notes_path.open("r", encoding="utf-8") as f:
            data = json.load(f)  # 损坏则抛异常终止,绝不覆盖坏档案
        if not isinstance(data, dict):
            raise ValueError("notes.json 顶层不是对象")
        for key, default in DEFAULT_NOTES.items():
            data.setdefault(key, json.loads(json.dumps(default)))
        return data

    def save_notes(self, data):
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        json.loads(serialized)  # 回读校验
        self.base.mkdir(parents=True, exist_ok=True)
        tmp = self.notes_path.with_suffix(".json.tmp")
        tmp.write_text(serialized + "\n", encoding="utf-8")
        os.replace(tmp, self.notes_path)

    def append_session(self, record):
        line = json.dumps(record, ensure_ascii=False)
        json.loads(line)  # 回读校验
        self.base.mkdir(parents=True, exist_ok=True)
        with self.sessions_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    def read_sessions(self):
        if not self.sessions_path.exists():
            return []
        records = []
        with self.sessions_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records


def cmd_record(ledger, args):
    src = Path(args.session_json)
    if not src.is_file():
        return emit({"error": "文件不存在: %s" % src}, 1)
    try:
        record = json.loads(src.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return emit({"error": "session json 不合法: %s" % e}, 1)
    if not isinstance(record, dict):
        return emit({"error": "session 记录必须是 JSON 对象"}, 1)
    record = {k: v for k, v in record.items() if not k.startswith("_")}

    warnings = []
    if "date" not in record:
        record["date"] = today()
        warnings.append("记录缺 date 字段,已补今天")
    for key in ("scale", "active_min", "user_turns", "tokens"):
        if key not in record:
            warnings.append("记录缺 %s 字段" % key)
    if not record.get("session_id"):
        warnings.append("记录缺 session_id,下次复盘无法定位本段边界(周报仍可用)")

    # 报告全文归档:周报靠它做交叉汇总,没有报告的记录只剩数字
    if args.report:
        record["report_path"] = ledger.archive_report(args.report, record)
    else:
        warnings.append("未提供 --report,本次报告全文没有归档,周报将缺少这一段素材")

    ledger.append_session(record)
    return emit({"recorded": True, "date": record["date"],
                 "report_path": record.get("report_path"), "warnings": warnings})


def cmd_last_covered(ledger, args):
    """上次对这个会话复盘覆盖到哪儿——同一个 session 常横跨数天、包含多段工作。"""
    matched = [
        r for r in ledger.read_sessions() if r.get("session_id") == args.session_id
    ]
    if not matched:
        return emit({"covered": False, "session_id": args.session_id})
    last = matched[-1]
    segment = last.get("segment") or {}
    return emit(
        {
            "covered": True,
            "session_id": args.session_id,
            "last_date": last.get("date"),
            "last_to_ts": segment.get("to_ts"),
            "last_turns": segment.get("turns"),
            "times_reviewed": len(matched),
        }
    )


def cmd_suggest(ledger, args):
    """记一条给过的建议。**纯追加日志,没有状态**。

    早期版本给每条建议记 pending/已实践/失败/放弃 四态,还算了个"实践率"。
    删掉的原因:那要求用户每次复盘都回来更新状态,而没人会这么做,
    结果是指标永远难看,反而制造愧疚。现在只记"什么时候给过什么建议",
    有没有用交给 `effect` 用真实数字判断。
    """
    data = ledger.load_notes()
    entry = {"date": args.date or today(), "text": args.add}
    if args.check:
        entry["check"] = args.check
    if args.session_id:
        entry["session_id"] = args.session_id
    data["suggestions"].append(entry)
    ledger.save_notes(data)
    return emit({"added": True, "entry": entry, "total": len(data["suggestions"])})


def cmd_suggestions(ledger, args):
    items = ledger.load_notes()["suggestions"]
    if args.days:
        cutoff = (date.today() - timedelta(days=args.days)).isoformat()
        items = [s for s in items if (s.get("date") or "") >= cutoff]
    return emit({"count": len(items), "suggestions": items})


NUMERIC_METRICS = ("active_min", "duration_min", "user_turns", "correction_turns")
TOKEN_METRICS = ("input", "output", "cache_read", "cache_write")


def _medians(records):
    """一批记录的各指标中位数。用中位数不用均值:一次跑飞的会话不该拉走基线。"""
    medians = {}
    for key in NUMERIC_METRICS:
        vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
        if vals:
            medians[key] = statistics.median(vals)
    for key in TOKEN_METRICS:
        vals = [
            r["tokens"][key]
            for r in records
            if isinstance(r.get("tokens"), dict)
            and isinstance(r["tokens"].get(key), (int, float))
        ]
        if vals:
            medians["tokens." + key] = statistics.median(vals)
    return medians


def _num(record, dotted):
    cur = record
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, (int, float)) else None


def cmd_baseline(ledger, args):
    records = [r for r in ledger.read_sessions() if scale_of(r) == args.scale]
    if len(records) < BASELINE_MIN_RECORDS:
        return emit({"ready": False, "count": len(records), "needed": BASELINE_MIN_RECORDS})
    return emit(
        {"ready": True, "count": len(records), "scale": args.scale,
         "medians": _medians(records)}
    )


def cmd_compare(ledger, args):
    """本次 vs 你自己在同规模任务上的中位数。

    "应有值"没有通用答案——大任务花小任务十倍 token 是正常的。
    唯一站得住的分母是你自己同规模的历史,所以不够 10 条就不出数。
    """
    try:
        session = json.loads(Path(args.session_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return emit({"error": "读取 session-json 失败: %s" % exc}, 1)
    records = [r for r in ledger.read_sessions() if scale_of(r) == args.scale]
    if len(records) < BASELINE_MIN_RECORDS:
        return emit(
            {
                "ready": False,
                "count": len(records),
                "needed": BASELINE_MIN_RECORDS,
                "note": "同规模记录不足,本次不要在报告里提超标——没有分母就没有超标。"
                        "这是新用户的正常状态,不用解释机制,也不用道歉",
            }
        )
    medians = _medians(records)
    deltas, flagged = {}, []
    for key, median in medians.items():
        value = _num(session, key)
        if value is None or not median:
            continue
        ratio = round(value / median, 2)
        deltas[key] = {"value": value, "baseline_median": median, "ratio": ratio,
                       "direction": "above" if ratio > 1 else "below"}
        if ratio >= COMPARE_FLAG_RATIO:
            flagged.append(key)
    return emit(
        {
            "ready": True,
            "scale": args.scale,
            "baseline_count": len(records),
            "deltas": deltas,
            "flagged": flagged,
            "note": "偏差只负责开启调查,不负责下结论。flagged 的指标要去 prompts[] 里"
                    "找出是哪一轮造成的、行为原因是什么,找不到就不要写进报告。"
                    "只说倍数,不要换算成美元",
        }
    )


def cmd_effect(ledger, args):
    """某个时间点前后的实测对比——把"那次改动到底有没有用"变成可证伪的。

    按日期切分,不依赖任何状态机:你说"我 8 月 4 号开始按建议改了",
    它就比 8 月 4 号前后同规模会话的实测中位数。
    """
    pivot = args.since
    try:
        datetime.strptime(pivot, "%Y-%m-%d")
    except ValueError:
        return emit({"error": "--since 需要 YYYY-MM-DD 格式,收到: %s" % pivot}, 1)
    records = [r for r in ledger.read_sessions() if r.get("date")]
    if args.scale:
        records = [r for r in records if scale_of(r) == args.scale]
    before = [r for r in records if r["date"] < pivot]
    after = [r for r in records if r["date"] >= pivot]
    m_before, m_after = _medians(before), _medians(after)
    changes = {}
    for key, bval in m_before.items():
        aval = m_after.get(key)
        if aval is None or not bval:
            continue
        changes[key] = {"before": bval, "after": aval,
                        "delta_pct": round((aval - bval) / bval * 100, 1)}
    reliable = len(before) >= EFFECT_MIN_PER_SIDE and len(after) >= EFFECT_MIN_PER_SIDE
    return emit(
        {
            "pivot_date": pivot,
            "scale": args.scale,
            "before": {"n": len(before), "medians": m_before},
            "after": {"n": len(after), "medians": m_after},
            "changes": changes,
            "reliable": reliable,
            "caveat": "两侧都是实测值,数字可以直接陈述;但每侧不足 %d 条时,"
                      "只能说前后有变化,不能说变化是那次改动带来的" % EFFECT_MIN_PER_SIDE,
        }
    )


def cmd_weekly_pack(ledger, args):
    """组装周报所需的素材(确定性部分),交叉汇总的文字由 LLM 读报告全文来写。"""
    cutoff = (date.today() - timedelta(days=args.days)).isoformat()
    records = [r for r in ledger.read_sessions() if (r.get("date") or "") >= cutoff]

    by_project = {}
    flag_sessions = {}
    for r in records:
        key = r.get("project") or r.get("task_summary") or "unknown"
        agg = by_project.setdefault(
            key, {"sessions": 0, "active_min": 0, "user_turns": 0, "output_tokens": 0,
                  "scales": []}
        )
        agg["sessions"] += 1
        for field, dotted in (("active_min", "active_min"), ("user_turns", "user_turns"),
                              ("output_tokens", "tokens.output")):
            v = _num(r, dotted)
            if v:
                agg[field] += v
        s = scale_of(r)
        if s:
            agg["scales"].append(s)
        for flag in r.get("waste_flags") or []:
            flag_sessions.setdefault(flag, []).append(r.get("date"))

    # 同一个问题在本周 ≥2 段里出现 = 复发,这是周报最有价值的一栏
    recurring = {f: d for f, d in flag_sessions.items() if len(d) >= 2}

    reports = [r.get("report_path") for r in records if r.get("report_path")]
    return emit(
        {
            "period": {"from": cutoff, "to": today(), "days": args.days},
            "coverage": ledger.coverage(cutoff, records),
            "session_count": len(records),
            "sessions": [
                {
                    "date": r.get("date"),
                    "project": r.get("project"),
                    "task_summary": r.get("task_summary"),
                    "scale": scale_of(r),
                    "active_min": _num(r, "active_min"),
                    "user_turns": _num(r, "user_turns"),
                    "waste_flags": r.get("waste_flags") or [],
                    "report_path": r.get("report_path"),
                }
                for r in records
            ],
            "by_project": by_project,
            "recurring_waste": recurring,
            "recent_suggestions": [
                s for s in ledger.load_notes()["suggestions"]
                if (s.get("date") or "") >= cutoff
            ],
            "reports_to_read": reports,
            "reports_missing": len(records) - len(reports),
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", help="档案目录(默认 ~/.claude/vibecoding-retro)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="把本次复盘的记录和报告全文入档")
    p.add_argument("--session-json", required=True)
    p.add_argument("--report", help="报告 markdown 文件;不给的话周报里这段只剩数字")

    p = sub.add_parser("last-covered", help="上次对该会话复盘覆盖到哪儿(增量复盘用)")
    p.add_argument("--session-id", required=True)

    p = sub.add_parser("suggest", help="记一条给过的建议(纯追加,无状态)")
    p.add_argument("--add", required=True, metavar="TEXT", help="建议本身,写人话")
    p.add_argument("--check", help="下次看什么数据判断它有没有用")
    p.add_argument("--session-id")
    p.add_argument("--date", help="默认今天")

    p = sub.add_parser("suggestions", help="列出给过的建议")
    p.add_argument("--days", type=int, help="只看最近 N 天")

    p = sub.add_parser("weekly-pack", help="组装周报素材(会话汇总+项目对比+复发问题)")
    p.add_argument("--days", type=int, default=7)

    p = sub.add_parser("baseline", help="同规模任务的个人中位数")
    p.add_argument("--scale", required=True, choices=SCALES)

    p = sub.add_parser("compare", help="本次 vs 同规模个人中位数(超出几倍)")
    p.add_argument("--session-json", required=True, help="parse_session.py 的输出文件")
    p.add_argument("--scale", required=True, choices=SCALES)

    p = sub.add_parser("effect", help="某个日期前后的实测对比")
    p.add_argument("--since", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--scale", choices=SCALES, help="限定规模可比性更强,但样本更少")

    args = parser.parse_args(argv)
    ledger = Ledger(Path(args.dir) if args.dir else default_dir())

    handlers = {
        "record": cmd_record,
        "last-covered": cmd_last_covered,
        "suggest": cmd_suggest,
        "suggestions": cmd_suggestions,
        "weekly-pack": cmd_weekly_pack,
        "baseline": cmd_baseline,
        "compare": cmd_compare,
        "effect": cmd_effect,
    }
    try:
        return handlers[args.command](ledger, args)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        return emit({"error": "档案操作失败,档案未改动: %s" % e}, 1)


if __name__ == "__main__":
    sys.exit(main())
