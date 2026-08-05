"""ledger.py 测试。运行:python -m unittest discover tests

这里刻意没有状态机测试——早期版本的"缺口台账"(观察→确认→结构性→毕业)已删,
理由见 ledger.py 模块 docstring。现在只测四件事:报告归档、增量边界、建议日志、周报素材。
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "vibecoding-retro" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ledger  # noqa: E402


def run(base_dir, *args):
    """调用 ledger CLI,返回 (exit_code, 解析后的 stdout JSON)。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = ledger.main(["--dir", str(base_dir)] + list(args))
    out = buf.getvalue().strip()
    return code, json.loads(out) if out else None


class LedgerTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def write_json(self, name, obj):
        p = self.dir / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def write_report(self, name, text):
        p = self.dir / name
        p.write_text(text, encoding="utf-8")
        return str(p)

    def record(self, name, **fields):
        fields.setdefault("date", date.today().isoformat())
        fields.setdefault("scale", "medium")
        return self.write_json(name, fields)


class TestReportArchive(LedgerTestCase):
    """报告全文必须归档——它是周报唯一的素材来源。"""

    def test_report_is_copied_and_path_recorded(self):
        sess = self.record("s.json", session_id="abc12345", project="/demo")
        rpt = self.write_report("r.md", "# 复盘\n正文")
        code, out = run(self.dir, "record", "--session-json", sess, "--report", rpt)
        self.assertEqual(code, 0)
        self.assertTrue(out["recorded"])
        self.assertTrue(out["report_path"].startswith("reports/"))
        archived = self.dir / out["report_path"]
        self.assertEqual(archived.read_text(encoding="utf-8"), "# 复盘\n正文")

    def test_missing_report_warns_loudly(self):
        sess = self.record("s.json", session_id="abc")
        _, out = run(self.dir, "record", "--session-json", sess)
        self.assertIsNone(out["report_path"])
        self.assertTrue(any("周报" in w for w in out["warnings"]))

    def test_same_session_twice_does_not_overwrite(self):
        for i in (1, 2):
            sess = self.record("s%d.json" % i, session_id="abc12345", project="/demo")
            rpt = self.write_report("r%d.md" % i, "第 %d 段" % i)
            _, out = run(self.dir, "record", "--session-json", sess, "--report", rpt)
        files = sorted(p.name for p in (self.dir / "reports").glob("*.md"))
        self.assertEqual(len(files), 2, "同一天同一会话复盘两段应各存一份")

    def test_empty_report_is_rejected_and_nothing_written(self):
        sess = self.record("s.json", session_id="abc")
        rpt = self.write_report("empty.md", "   \n")
        code, out = run(self.dir, "record", "--session-json", sess, "--report", rpt)
        self.assertEqual(code, 1)
        self.assertIn("为空", out["error"])
        self.assertFalse((self.dir / "sessions.jsonl").exists())

    def test_corrupt_session_json_is_rejected(self):
        p = self.dir / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        code, out = run(self.dir, "record", "--session-json", str(p))
        self.assertEqual(code, 1)
        self.assertIn("不合法", out["error"])


class TestSegmentBoundary(LedgerTestCase):
    """一个 session 常横跨数天,复盘多次;边界靠 segment 记住,免得重复看。"""

    def test_uncovered_session(self):
        _, out = run(self.dir, "last-covered", "--session-id", "never-seen")
        self.assertFalse(out["covered"])

    def test_returns_latest_boundary(self):
        for i, ts in enumerate(("2026-08-01T10:00:00Z", "2026-08-02T10:00:00Z")):
            sess = self.record(
                "s%d.json" % i, session_id="sid-1",
                segment={"from_ts": "2026-08-01T09:00:00Z", "to_ts": ts, "turns": [1, 5 * (i + 1)]},
            )
            run(self.dir, "record", "--session-json", sess)
        _, out = run(self.dir, "last-covered", "--session-id", "sid-1")
        self.assertTrue(out["covered"])
        self.assertEqual(out["last_to_ts"], "2026-08-02T10:00:00Z")
        self.assertEqual(out["times_reviewed"], 2)


class TestSuggestionsLog(LedgerTestCase):
    """建议是纯追加日志,没有状态——用户不必回来更新任何东西。"""

    def test_append_and_list(self):
        code, out = run(self.dir, "suggest", "--add", "把这两个文件的职责写进 CLAUDE.md",
                        "--check", "下次看重复读文件还在不在", "--session-id", "sid-1")
        self.assertEqual(code, 0)
        self.assertTrue(out["added"])
        _, out = run(self.dir, "suggestions")
        self.assertEqual(out["count"], 1)
        entry = out["suggestions"][0]
        self.assertIn("CLAUDE.md", entry["text"])
        self.assertIn("重复读文件", entry["check"])

    def test_no_status_field_exists(self):
        run(self.dir, "suggest", "--add", "随便一条")
        _, out = run(self.dir, "suggestions")
        entry = out["suggestions"][0]
        for dead in ("status", "practice_rate", "tried"):
            self.assertNotIn(dead, entry, "建议不该有状态字段,那是删掉的设计")

    def test_days_filter(self):
        run(self.dir, "suggest", "--add", "老的", "--date", "2020-01-01")
        run(self.dir, "suggest", "--add", "新的")
        _, out = run(self.dir, "suggestions", "--days", "7")
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["suggestions"][0]["text"], "新的")

    def test_duplicates_are_allowed(self):
        # 同一条建议给过两次是真实信息(说明没生效),不该被去重掉
        run(self.dir, "suggest", "--add", "同一条")
        run(self.dir, "suggest", "--add", "同一条")
        _, out = run(self.dir, "suggestions")
        self.assertEqual(out["count"], 2)


class TestBaselineAndCompare(LedgerTestCase):
    """分母只能是用户自己同规模的历史,不是任何行业基准。"""

    def _seed(self, n, active_min=40, scale="medium"):
        sess = self.record("seed.json", scale=scale, active_min=active_min, user_turns=10,
                           tokens={"input": 1000, "output": 500, "cache_read": 0, "cache_write": 0})
        for _ in range(n):
            run(self.dir, "record", "--session-json", sess)

    def test_baseline_not_ready_below_threshold(self):
        self._seed(4)
        _, out = run(self.dir, "baseline", "--scale", "medium")
        self.assertFalse(out["ready"])
        self.assertEqual(out["count"], 4)

    def test_compare_refuses_without_enough_history(self):
        self._seed(4)
        cur = self.write_json("cur.json", {"active_min": 120})
        _, out = run(self.dir, "compare", "--session-json", cur, "--scale", "medium")
        self.assertFalse(out["ready"])
        # 没有分母时必须明确禁止在报告里提超标,而且不要用户道歉
        self.assertIn("超标", out["note"])
        self.assertIn("正常状态", out["note"])

    def test_ratio_and_flagging(self):
        self._seed(10, active_min=40)
        cur = self.write_json("cur.json", {"active_min": 80, "user_turns": 10})
        _, out = run(self.dir, "compare", "--session-json", cur, "--scale", "medium")
        self.assertTrue(out["ready"])
        self.assertEqual(out["deltas"]["active_min"]["ratio"], 2.0)
        self.assertIn("active_min", out["flagged"])
        self.assertEqual(out["deltas"]["user_turns"]["ratio"], 1.0)
        self.assertNotIn("user_turns", out["flagged"])

    def test_note_sends_you_back_to_per_turn_ledger(self):
        self._seed(10)
        cur = self.write_json("cur.json", {"active_min": 80})
        _, out = run(self.dir, "compare", "--session-json", cur, "--scale", "medium")
        self.assertIn("prompts[]", out["note"])
        self.assertIn("美元", out["note"])

    def test_legacy_complexity_records_still_count(self):
        # 旧记录用 complexity: S/M/L,不该因为改名就丢掉历史
        legacy = self.write_json("legacy.json", {"date": date.today().isoformat(),
                                                 "complexity": "M", "active_min": 40})
        for _ in range(10):
            run(self.dir, "record", "--session-json", legacy)
        _, out = run(self.dir, "baseline", "--scale", "medium")
        self.assertTrue(out["ready"])
        self.assertEqual(out["count"], 10)


class TestEffect(LedgerTestCase):
    """按日期切分的前后实测对比,不依赖任何状态机。"""

    def _record(self, name, date_str, active_min):
        sess = self.write_json(name, {"date": date_str, "scale": "medium",
                                      "active_min": active_min, "user_turns": 10})
        run(self.dir, "record", "--session-json", sess)

    def test_bad_date_rejected(self):
        code, out = run(self.dir, "effect", "--since", "八月四号")
        self.assertEqual(code, 1)
        self.assertIn("YYYY-MM-DD", out["error"])

    def test_measures_change_around_pivot(self):
        for i, m in enumerate((60, 62, 58)):
            self._record("b%d.json" % i, "2026-07-0%d" % (i + 1), m)
        pivot = date.today().isoformat()
        for i, m in enumerate((40, 42, 38)):
            self._record("a%d.json" % i, pivot, m)
        _, out = run(self.dir, "effect", "--since", pivot, "--scale", "medium")
        self.assertEqual(out["before"]["n"], 3)
        self.assertEqual(out["after"]["n"], 3)
        self.assertEqual(out["changes"]["active_min"]["before"], 60)
        self.assertEqual(out["changes"]["active_min"]["after"], 40)
        self.assertAlmostEqual(out["changes"]["active_min"]["delta_pct"], -33.3, places=1)
        self.assertTrue(out["reliable"])

    def test_small_sample_marked_unreliable(self):
        self._record("b.json", "2026-07-01", 60)
        pivot = date.today().isoformat()
        self._record("a.json", pivot, 40)
        _, out = run(self.dir, "effect", "--since", pivot)
        self.assertFalse(out["reliable"])
        self.assertIn("不能说", out["caveat"])


class TestWeeklyPack(LedgerTestCase):
    def _record(self, name, project, flags, report=None, session_id=None):
        fields = {"date": date.today().isoformat(), "scale": "medium", "project": project,
                  "active_min": 30, "user_turns": 12, "waste_flags": flags,
                  "tokens": {"output": 1000}}
        if session_id:
            fields["session_id"] = session_id
        sess = self.write_json(name, fields)
        args = ["record", "--session-json", sess]
        if report:
            args += ["--report", self.write_report(name + ".md", report)]
        run(self.dir, *args)

    def test_recurring_problems_need_two_sessions(self):
        self._record("a", "/p1", ["repeated-file-read", "context-bloat"])
        self._record("b", "/p2", ["repeated-file-read"])
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertIn("repeated-file-read", out["recurring_waste"])
        self.assertNotIn("context-bloat", out["recurring_waste"],
                         "只出现一次的问题属于当次报告,不进周报")

    def test_by_project_aggregation(self):
        self._record("a", "/p1", [])
        self._record("b", "/p1", [])
        self._record("c", "/p2", [])
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["by_project"]["/p1"]["sessions"], 2)
        self.assertEqual(out["by_project"]["/p1"]["active_min"], 60)
        self.assertEqual(out["by_project"]["/p2"]["sessions"], 1)

    def test_missing_reports_are_counted_honestly(self):
        self._record("a", "/p1", [], report="# 有报告")
        self._record("b", "/p1", [])
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(len(out["reports_to_read"]), 1)
        self.assertEqual(out["reports_missing"], 1)

    def test_old_records_excluded(self):
        old = self.write_json("old.json", {"date": "2020-01-01", "project": "/p"})
        run(self.dir, "record", "--session-json", old)
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["session_count"], 0)

    def test_recent_suggestions_included(self):
        run(self.dir, "suggest", "--add", "本周给过的建议")
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(len(out["recent_suggestions"]), 1)

    def test_no_dead_keys_from_the_old_design(self):
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        for dead in ("gaps", "graduated", "practice_rate", "tips_to_try", "missing_terms"):
            self.assertNotIn(dead, out, "%s 属于已删掉的台账设计" % dead)


class TestCoverage(LedgerTestCase):
    """忘了复盘的会话必须现形,不能默认当成 100%。"""

    def _index(self, entries):
        (self.dir / "session-index.jsonl").write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )

    def test_unavailable_without_hook(self):
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertFalse(out["coverage"]["available"])

    def test_counts_sessions_never_retroed(self):
        ts = date.today().isoformat() + "T10:00:00+00:00"
        self._index([{"session_id": s, "project": "/p", "ts": ts} for s in ("s1", "s2", "s3")])
        sess = self.write_json("r.json", {"date": date.today().isoformat(),
                                          "session_id": "s1", "project": "/p"})
        run(self.dir, "record", "--session-json", sess)
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        cov = out["coverage"]
        self.assertEqual(cov["sessions_seen"], 3)
        self.assertEqual(cov["sessions_retroed"], 1)
        self.assertEqual({m["session_id"] for m in cov["not_retroed"]}, {"s2", "s3"})

    def test_old_index_entries_excluded(self):
        self._index([{"session_id": "old", "ts": "2020-01-01T00:00:00+00:00"}])
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["coverage"]["sessions_seen"], 0)


class TestSessionEndHook(unittest.TestCase):
    """钩子只登记一行,且任何情况下都不能吵。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, stdin_text):
        hook = Path(__file__).resolve().parent.parent / "hooks" / "session_end_index.py"
        env = dict(os.environ, VIBECODING_RETRO_HOME=str(self.dir))
        return subprocess.run([sys.executable, str(hook)], input=stdin_text,
                              capture_output=True, text=True, env=env)

    def test_appends_pointer_line(self):
        r = self._run(json.dumps({"session_id": "abc", "cwd": "/proj",
                                  "transcript_path": "/log.jsonl"}))
        self.assertEqual(r.returncode, 0)
        lines = (self.dir / "session-index.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["session_id"], "abc")

    def test_garbage_input_is_silent(self):
        r = self._run("not json at all")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.assertFalse((self.dir / "session-index.jsonl").exists())

    def test_missing_session_id_writes_nothing(self):
        r = self._run(json.dumps({"cwd": "/proj"}))
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.dir / "session-index.jsonl").exists())
