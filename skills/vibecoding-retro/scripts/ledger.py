#!/usr/bin/env python3
"""vibecoding-retro 台账状态机。仅标准库,零依赖。输出 JSON 到 stdout。

档案目录:~/.claude/vibecoding-retro/(可用 --dir 或环境变量 VIBECODING_RETRO_HOME 覆盖)
  sessions.jsonl    历史会话记录(append-only,每条含 report_path 指向报告全文)
  gap-ledger.json   缺口台账 + tips_to_try 待实践清单 + missing_terms 词汇台账
  reports/          每次复盘的报告全文(markdown),周报的交叉素材

状态转移规则(以 references/capability-diagnosis.md 为准):
  count(=用户确认数) >= 3           → structural
  user_rejected >= 2                 → suppressed(停检)
  structural 且连续 5 次 session 未现 → graduated

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

# 状态转移阈值
STRUCTURAL_CONFIRMS = 3
SUPPRESS_REJECTS = 2
GRADUATE_ABSENT_SESSIONS = 5
CLUSTER_MIN_TERMS = 3
BASELINE_MIN_RECORDS = 10
COMPARE_FLAG_RATIO = 1.5      # 本次达到个人中位数的 N 倍才值得去查,低于此值是正常波动
EFFECT_MIN_PER_SIDE = 3       # 建议前后对比,每侧至少 N 条才敢说"看得出变化"

TIP_STATUSES = ("pending", "tried-worked", "tried-failed", "skipped")

DEFAULT_LEDGER = {"gaps": {}, "graduated": {}, "tips_to_try": [], "missing_terms": []}


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


class Ledger:
    def __init__(self, base_dir):
        self.base = Path(base_dir)
        self.ledger_path = self.base / "gap-ledger.json"
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
        """本周有多少段会话发生过、其中多少段真的复盘了。

        素材来自 SessionEnd 钩子写的 session-index.jsonl(只登记会话存在,不做分析)。
        钩子没装时返回 available:false——**不要因此假装覆盖率是 100%**,
        忘了复盘的会话是隐形的,这个功能就是为了让它们现形。
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

    def load(self):
        if not self.ledger_path.exists():
            return json.loads(json.dumps(DEFAULT_LEDGER))
        with self.ledger_path.open("r", encoding="utf-8") as f:
            data = json.load(f)  # 损坏则抛异常终止,绝不覆盖坏档案
        if not isinstance(data, dict):
            raise ValueError("gap-ledger.json 顶层不是对象")
        for key, default in DEFAULT_LEDGER.items():
            data.setdefault(key, json.loads(json.dumps(default)))
        return data

    def save(self, data):
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        json.loads(serialized)  # 回读校验
        self.base.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger_path.with_suffix(".json.tmp")
        tmp.write_text(serialized + "\n", encoding="utf-8")
        os.replace(tmp, self.ledger_path)

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


def new_gap():
    return {
        "count": 0,
        "dates": [],
        "user_confirmed": 0,
        "user_rejected": 0,
        "status": "watching",
        "sessions_since_last_seen": 0,
    }


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
    for key in ("env", "complexity", "active_min", "user_turns", "tokens"):
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

    # 毕业计数:本次 session 未出现的缺口,连续未现次数 +1;出现则清零
    data = ledger.load()
    mentioned = {
        d.get("gap_id")
        for d in record.get("diagnoses", [])
        if isinstance(d, dict) and d.get("gap_id")
    }
    for gap_id, gap in data["gaps"].items():
        if gap.get("status") == "suppressed":
            continue
        if gap_id in mentioned:
            gap["sessions_since_last_seen"] = 0
        else:
            gap["sessions_since_last_seen"] = gap.get("sessions_since_last_seen", 0) + 1
    ledger.save(data)

    return emit(
        {
            "recorded": True,
            "date": record["date"],
            "report_path": record.get("report_path"),
            "warnings": warnings,
        }
    )


def cmd_last_covered(ledger, args):
    """上次对该会话复盘覆盖到哪儿——下次只诊断增量,避免重复诊断同一段。"""
    matches = [
        r for r in ledger.read_sessions() if r.get("session_id") == args.session_id
    ]
    if not matches:
        return emit({"covered": False, "session_id": args.session_id})
    last = matches[-1]
    seg = last.get("segment") or {}
    return emit(
        {
            "covered": True,
            "session_id": args.session_id,
            "segments": len(matches),
            "last_date": last.get("date"),
            "last_to_ts": seg.get("to_ts"),
            "last_turn": (seg.get("turns") or [None, None])[1],
            "report_path": last.get("report_path"),
        }
    )


def cmd_confirm(ledger, args, confirmed):
    data = ledger.load()
    gap = data["gaps"].setdefault(args.gap, new_gap())
    d = args.date or today()
    if confirmed:
        gap["count"] += 1
        gap["user_confirmed"] += 1
        gap.setdefault("dates", []).append(d)
        gap["sessions_since_last_seen"] = 0
    else:
        gap["user_rejected"] += 1
    ledger.save(data)
    return emit({"gap": args.gap, **gap})


def apply_transitions(data):
    """执行状态转移,返回变更列表。"""
    changes = []
    for gap_id in list(data["gaps"].keys()):
        gap = data["gaps"][gap_id]
        status = gap.get("status", "watching")
        if status != "suppressed" and gap.get("user_rejected", 0) >= SUPPRESS_REJECTS:
            gap["status"] = "suppressed"
            changes.append({"gap": gap_id, "from": status, "to": "suppressed"})
            continue
        if status == "watching" and gap.get("count", 0) >= STRUCTURAL_CONFIRMS:
            gap["status"] = "structural"
            status = "structural"
            changes.append({"gap": gap_id, "from": "watching", "to": "structural"})
        if (
            status == "structural"
            and gap.get("sessions_since_last_seen", 0) >= GRADUATE_ABSENT_SESSIONS
        ):
            data["graduated"][gap_id] = {
                "resolved_date": today(),
                "note": "连续%d次session未出现" % gap["sessions_since_last_seen"],
            }
            del data["gaps"][gap_id]
            changes.append({"gap": gap_id, "from": "structural", "to": "graduated"})
    return changes


def cmd_status(ledger, args):
    data = ledger.load()
    changes = apply_transitions(data)
    if changes:
        ledger.save(data)
    return emit(
        {
            "gaps": data["gaps"],
            "graduated": data["graduated"],
            "transitions": changes,
        }
    )


def cmd_tips(ledger, args):
    data = ledger.load()
    tips = data["tips_to_try"]
    if args.add:
        kb_id = args.add
        existing = [t for t in tips if t.get("kb_id") == kb_id and t.get("status") == "pending"]
        if existing:
            if args.note:  # 已在清单中时,--note 视为补写具体动作
                existing[-1]["note"] = args.note
                ledger.save(data)
                return emit({"added": False, "kb_id": kb_id, "note_updated": True})
            return emit({"added": False, "reason": "%s 已在待实践清单中" % kb_id})
        entry = {"kb_id": kb_id, "date_added": today(), "status": "pending"}
        if args.note:
            entry["note"] = args.note
        tips.append(entry)
        ledger.save(data)
        return emit({"added": True, "kb_id": kb_id})
    if args.set:
        kb_id, status = args.set
        if status not in TIP_STATUSES:
            return emit({"error": "非法状态 %s,可选: %s" % (status, "/".join(TIP_STATUSES))}, 1)
        matched = [t for t in tips if t.get("kb_id") == kb_id]
        if not matched:
            return emit({"error": "%s 不在清单中,先用 --add 添加" % kb_id}, 1)
        matched[-1]["status"] = status
        matched[-1]["date_updated"] = today()
        if args.note:
            matched[-1]["note"] = args.note
        ledger.save(data)
        return emit({"kb_id": kb_id, "status": status})
    if args.pending:
        return emit([t for t in tips if t.get("status") == "pending"])
    return emit({"tips_to_try": tips})


def cmd_practice_rate(ledger, args):
    tips = ledger.load()["tips_to_try"]
    active = [t for t in tips if t.get("status") != "skipped"]
    tried = [t for t in active if t.get("status") in ("tried-worked", "tried-failed")]
    rate = round(len(tried) / len(active), 4) if active else None
    return emit(
        {
            "practice_rate": rate,
            "tried": len(tried),
            "active": len(active),
            "skipped": len(tips) - len(active),
        }
    )


def cmd_terms(ledger, args):
    data = ledger.load()
    terms = data["missing_terms"]
    if args.add:
        if not args.domain:
            return emit({"error": "terms --add 必须带 --domain"}, 1)
        if any(t.get("term") == args.add for t in terms):
            return emit({"added": False, "note": "%s 已在词汇台账中" % args.add})
        terms.append({"term": args.add, "domain": args.domain, "date": today()})
        ledger.save(data)
        return emit({"added": True, "term": args.add, "domain": args.domain})
    if args.clusters:
        by_domain = {}
        for t in terms:
            by_domain.setdefault(t.get("domain") or "unknown", []).append(t.get("term"))
        clusters = {d: ts for d, ts in by_domain.items() if len(ts) >= CLUSTER_MIN_TERMS}
        return emit({"clusters": clusters, "total_terms": len(terms)})
    return emit({"missing_terms": terms})


NUMERIC_METRICS = ("active_min", "duration_min", "user_turns", "correction_turns")
TOKEN_METRICS = ("input", "output", "cache_read", "cache_write", "cost_usd")


def _medians(records):
    """一批记录的各指标中位数。中位数不是均值:一次跑飞的会话不该拉走基线。"""
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
    overall = [
        r["scores"]["overall"]
        for r in records
        if isinstance(r.get("scores"), dict)
        and isinstance(r["scores"].get("overall"), (int, float))
    ]
    if overall:
        medians["scores.overall"] = statistics.median(overall)
    return medians


def cmd_baseline(ledger, args):
    records = [r for r in ledger.read_sessions() if r.get("complexity") == args.complexity]
    if len(records) < BASELINE_MIN_RECORDS:
        return emit({"ready": False, "count": len(records)})
    return emit(
        {
            "ready": True,
            "count": len(records),
            "complexity": args.complexity,
            "medians": _medians(records),
        }
    )


def cmd_compare(ledger, args):
    """本次会话 vs 你自己在同复杂度上的中位数。

    "应有值"没有通用答案——L 级任务花 S 级十倍 token 是正常的。
    唯一站得住的分母是**你自己同档位的历史中位数**,所以基线不够 10 条时不出数。
    """
    try:
        session = json.loads(Path(args.session_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return emit({"error": "读取 session-json 失败: %s" % exc}, 1)
    records = [r for r in ledger.read_sessions() if r.get("complexity") == args.complexity]
    if len(records) < BASELINE_MIN_RECORDS:
        return emit(
            {
                "ready": False,
                "count": len(records),
                "needed": BASELINE_MIN_RECORDS,
                "note": "同档位记录不足,本次不要在报告里提超标——没有分母就没有超标",
            }
        )
    medians = _medians(records)
    deltas = {}
    flagged = []
    for key, median in medians.items():
        value = _num(session, key)
        if value is None or not median:
            continue
        ratio = round(value / median, 2)
        deltas[key] = {
            "value": value,
            "baseline_median": median,
            "ratio": ratio,
            "direction": "above" if ratio > 1 else "below",
        }
        if ratio >= COMPARE_FLAG_RATIO:
            flagged.append(key)
    return emit(
        {
            "ready": True,
            "complexity": args.complexity,
            "baseline_count": len(records),
            "deltas": deltas,
            "flagged": flagged,
            "note": (
                "偏差只负责开启调查,不负责下结论。flagged 的指标要去 prompts[] 里找到"
                "具体是哪一轮造成的、以及行为原因,找不到就不要写进诊断。"
                "另:只谈 token 与倍数,不要换算成美元——订阅制下那是估算的估算。"
            ),
        }
    )


def cmd_effect(ledger, args):
    """某条建议采纳前后的实测对比——把"这条建议到底有没有用"变成可证伪的。

    两边都是实测中位数,不是模拟,所以可以直接陈述;
    但样本少时相关≠因果,reliable=false 时报告必须说明这一点。
    """
    data = ledger.load()
    matched = [t for t in data["tips_to_try"] if t.get("kb_id") == args.tip]
    if not matched:
        return emit({"error": "%s 不在待实践清单中" % args.tip}, 1)
    tip = matched[-1]
    pivot = tip.get("date_updated") or tip.get("date_added")
    if not pivot:
        return emit({"error": "%s 没有日期,无法切分前后" % args.tip}, 1)
    records = [r for r in ledger.read_sessions() if r.get("date")]
    if args.complexity:
        records = [r for r in records if r.get("complexity") == args.complexity]
    before = [r for r in records if r["date"] < pivot]
    after = [r for r in records if r["date"] >= pivot]
    m_before, m_after = _medians(before), _medians(after)
    changes = {}
    for key, bval in m_before.items():
        aval = m_after.get(key)
        if aval is None or not bval:
            continue
        changes[key] = {
            "before": bval,
            "after": aval,
            "delta_pct": round((aval - bval) / bval * 100, 1),
        }
    reliable = len(before) >= EFFECT_MIN_PER_SIDE and len(after) >= EFFECT_MIN_PER_SIDE
    return emit(
        {
            "kb_id": args.tip,
            "status": tip.get("status"),
            "note": tip.get("note"),
            "pivot_date": pivot,
            "complexity": args.complexity,
            "before": {"n": len(before), "medians": m_before},
            "after": {"n": len(after), "medians": m_after},
            "changes": changes,
            "reliable": reliable,
            "caveat": (
                "两侧样本都是实测值,可以直接陈述数字;但每侧不足 %d 条时,只能说前后有变化,"
                "不能说变化是这条建议带来的" % EFFECT_MIN_PER_SIDE
            ),
        }
    )


def _num(record, dotted):
    cur = record
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, (int, float)) else None


def cmd_weekly_pack(ledger, args):
    """组装周报所需的全部素材(确定性部分),交叉汇总的文字由 LLM 按模板写。"""
    cutoff = (date.today() - timedelta(days=args.days)).isoformat()
    records = [r for r in ledger.read_sessions() if (r.get("date") or "") >= cutoff]
    data = ledger.load()

    by_project = {}
    flag_sessions = {}
    for r in records:
        key = r.get("project") or r.get("task_summary") or "unknown"
        agg = by_project.setdefault(
            key, {"sessions": 0, "active_min": 0, "user_turns": 0, "output_tokens": 0,
                  "complexities": [], "overall_scores": []}
        )
        agg["sessions"] += 1
        for field, dotted in (("active_min", "active_min"), ("user_turns", "user_turns"),
                              ("output_tokens", "tokens.output")):
            v = _num(r, dotted)
            if v:
                agg[field] += v
        if r.get("complexity"):
            agg["complexities"].append(r["complexity"])
        s = _num(r, "scores.overall")
        if s is not None:
            agg["overall_scores"].append(s)
        for flag in r.get("waste_flags") or []:
            flag_sessions.setdefault(flag, []).append(r.get("date"))

    for agg in by_project.values():
        agg["median_overall"] = (
            statistics.median(agg["overall_scores"]) if agg["overall_scores"] else None
        )
        del agg["overall_scores"]

    # 同一个坑在本周 ≥2 段里出现 = J4 候选(跨会话重复踩坑)
    recurring = {f: d for f, d in flag_sessions.items() if len(d) >= 2}

    tips = data["tips_to_try"]
    active = [t for t in tips if t.get("status") != "skipped"]
    tried = [t for t in active if t.get("status") in ("tried-worked", "tried-failed")]

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
                    "complexity": r.get("complexity"),
                    "active_min": _num(r, "active_min"),
                    "user_turns": _num(r, "user_turns"),
                    "overall": _num(r, "scores.overall"),
                    "waste_flags": r.get("waste_flags") or [],
                    "report_path": r.get("report_path"),
                }
                for r in records
            ],
            "by_project": by_project,
            "recurring_waste": recurring,
            "gaps": data["gaps"],
            "graduated": data["graduated"],
            "practice_rate": round(len(tried) / len(active), 4) if active else None,
            "tips_to_try": tips,
            "missing_terms": data["missing_terms"],
            "reports_to_read": [
                r["report_path"] for r in records if r.get("report_path")
            ],
            "reports_missing": sum(1 for r in records if not r.get("report_path")),
        }
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", help="档案目录(默认 ~/.claude/vibecoding-retro)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("record", help="追加一条会话记录到 sessions.jsonl")
    p.add_argument("--session-json", required=True)
    p.add_argument("--report", help="本次报告的 markdown 文件,会归档进 reports/ 供周报交叉汇总")

    p = sub.add_parser("last-covered", help="上次对该会话复盘覆盖到哪儿(增量复盘用)")
    p.add_argument("--session-id", required=True)

    p = sub.add_parser("weekly-pack", help="组装周报素材(会话汇总+项目对比+复发坑+台账)")
    p.add_argument("--days", type=int, default=7)

    for name in ("confirm", "reject"):
        p = sub.add_parser(name, help="用户确认/否决某缺口诊断")
        p.add_argument("--gap", required=True, help="缺口 ID,如 T4")
        p.add_argument("--date", help="默认今天")

    p = sub.add_parser("tips", help="待实践清单管理")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--add", metavar="KB_ID")
    g.add_argument("--set", nargs=2, metavar=("KB_ID", "STATUS"))
    g.add_argument("--pending", action="store_true")
    p.add_argument("--note", help="这条建议落到用户工作流上的具体动作(个性化落点,验证时按它核对)")

    sub.add_parser("practice-rate", help="建议实践率(北极星指标)")
    sub.add_parser("status", help="全部缺口状态,并执行状态转移")

    p = sub.add_parser("terms", help="词汇台账与聚类")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--add", metavar="TERM")
    g.add_argument("--clusters", action="store_true")
    p.add_argument("--domain", help="术语所属领域,--add 时必填")

    p = sub.add_parser("baseline", help="同复杂度档位个人基线")
    p.add_argument("--complexity", required=True, choices=["S", "M", "L"])

    p = sub.add_parser("compare", help="本次会话 vs 同档位个人基线(超出多少倍)")
    p.add_argument("--session-json", required=True, help="parse_session.py 的输出文件")
    p.add_argument("--complexity", required=True, choices=["S", "M", "L"])

    p = sub.add_parser("effect", help="某条建议采纳前后的实测对比")
    p.add_argument("--tip", required=True, metavar="KB_ID")
    p.add_argument("--complexity", choices=["S", "M", "L"], help="限定档位可比性更强,但样本更少")

    args = parser.parse_args(argv)
    ledger = Ledger(Path(args.dir) if args.dir else default_dir())

    try:
        if args.command == "record":
            return cmd_record(ledger, args)
        if args.command == "confirm":
            return cmd_confirm(ledger, args, confirmed=True)
        if args.command == "reject":
            return cmd_confirm(ledger, args, confirmed=False)
        if args.command == "tips":
            return cmd_tips(ledger, args)
        if args.command == "practice-rate":
            return cmd_practice_rate(ledger, args)
        if args.command == "status":
            return cmd_status(ledger, args)
        if args.command == "terms":
            return cmd_terms(ledger, args)
        if args.command == "baseline":
            return cmd_baseline(ledger, args)
        if args.command == "compare":
            return cmd_compare(ledger, args)
        if args.command == "effect":
            return cmd_effect(ledger, args)
        if args.command == "last-covered":
            return cmd_last_covered(ledger, args)
        if args.command == "weekly-pack":
            return cmd_weekly_pack(ledger, args)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        return emit({"error": "台账操作失败,档案未改动: %s" % e}, 1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
