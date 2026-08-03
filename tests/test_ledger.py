"""ledger.py 状态机测试:watching → structural → graduated 全程,及 rejected×2 → suppressed。"""
import contextlib
import os
import io
import json
import sys
import tempfile
from datetime import date
import unittest
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

    def write_session(self, name, record):
        p = self.dir / name
        p.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return str(p)


class TestGapLifecycle(LedgerTestCase):
    def test_watching_to_structural_to_graduated(self):
        # 确认 3 次 → structural
        for d in ("2026-07-01", "2026-07-05", "2026-07-08"):
            code, out = run(self.dir, "confirm", "--gap", "T4", "--date", d)
            self.assertEqual(code, 0)
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["status"], "watching")  # 转移在 status 时执行

        code, out = run(self.dir, "status")
        self.assertEqual(code, 0)
        self.assertEqual(out["gaps"]["T4"]["status"], "structural")
        self.assertIn({"gap": "T4", "from": "watching", "to": "structural"}, out["transitions"])

        # 连续 5 次 session 未出现 → graduated
        sess = self.write_session("s.json", {"date": "2026-07-10", "complexity": "M", "diagnoses": []})
        for _ in range(5):
            code, out = run(self.dir, "record", "--session-json", sess)
            self.assertEqual(code, 0)
            self.assertTrue(out["recorded"])

        code, out = run(self.dir, "status")
        self.assertEqual(code, 0)
        self.assertNotIn("T4", out["gaps"])
        self.assertIn("T4", out["graduated"])
        self.assertIn({"gap": "T4", "from": "structural", "to": "graduated"}, out["transitions"])

    def test_session_with_gap_resets_graduation_counter(self):
        for _ in range(3):
            run(self.dir, "confirm", "--gap", "T1")
        run(self.dir, "status")  # → structural

        absent = self.write_session("a.json", {"date": "2026-07-10", "diagnoses": []})
        present = self.write_session(
            "p.json", {"date": "2026-07-11", "diagnoses": [{"gap_id": "T1", "user_response": "confirmed"}]}
        )
        for _ in range(4):
            run(self.dir, "record", "--session-json", absent)
        run(self.dir, "record", "--session-json", present)  # 第 5 次出现了,计数清零

        code, out = run(self.dir, "status")
        self.assertIn("T1", out["gaps"])  # 未毕业
        self.assertEqual(out["gaps"]["T1"]["sessions_since_last_seen"], 0)

    def test_rejected_twice_suppressed(self):
        run(self.dir, "reject", "--gap", "T2")
        code, out = run(self.dir, "reject", "--gap", "T2")
        self.assertEqual(out["user_rejected"], 2)

        code, out = run(self.dir, "status")
        self.assertEqual(out["gaps"]["T2"]["status"], "suppressed")

    def test_corrupt_ledger_never_overwritten(self):
        ledger_file = self.dir / "gap-ledger.json"
        ledger_file.write_text("{corrupt!!", encoding="utf-8")
        code, out = run(self.dir, "confirm", "--gap", "T3")
        self.assertEqual(code, 1)
        self.assertIn("error", out)
        self.assertEqual(ledger_file.read_text(encoding="utf-8"), "{corrupt!!")  # 原样保留


class TestTipsAndPracticeRate(LedgerTestCase):
    def test_tips_flow_and_north_star(self):
        run(self.dir, "tips", "--add", "KB-24")
        code, out = run(self.dir, "tips", "--add", "KB-24")  # 重复添加被拒
        self.assertFalse(out["added"])
        run(self.dir, "tips", "--add", "KB-25")
        run(self.dir, "tips", "--add", "KB-26")

        code, out = run(self.dir, "tips", "--pending")
        self.assertEqual([t["kb_id"] for t in out], ["KB-24", "KB-25", "KB-26"])

        run(self.dir, "tips", "--set", "KB-24", "tried-worked")
        run(self.dir, "tips", "--set", "KB-26", "skipped")

        # 实践率 = tried / 非 skipped = 1 / 2
        code, out = run(self.dir, "practice-rate")
        self.assertEqual(out["practice_rate"], 0.5)
        self.assertEqual(out["tried"], 1)
        self.assertEqual(out["active"], 2)
        self.assertEqual(out["skipped"], 1)

    def test_note_records_personalized_action(self):
        run(self.dir, "tips", "--add", "KB-19", "--note", "HANDOFF 加进度段")
        code, out = run(self.dir, "tips", "--pending")
        self.assertEqual(out[0]["note"], "HANDOFF 加进度段")

        # 已在清单中时 --note 补写而非拒绝
        code, out = run(self.dir, "tips", "--add", "KB-19", "--note", "改成:写 PRODUCT.md")
        self.assertFalse(out["added"])
        self.assertTrue(out["note_updated"])
        code, out = run(self.dir, "tips", "--pending")
        self.assertEqual(out[0]["note"], "改成:写 PRODUCT.md")

        # --set 时也能带 note
        run(self.dir, "tips", "--set", "KB-19", "tried-worked", "--note", "已生效")
        code, out = run(self.dir, "tips")
        self.assertEqual(out["tips_to_try"][0]["note"], "已生效")
        self.assertEqual(out["tips_to_try"][0]["status"], "tried-worked")

    def test_set_unknown_tip_errors(self):
        code, out = run(self.dir, "tips", "--set", "KB-99", "tried-worked")
        self.assertEqual(code, 1)

    def test_invalid_status_rejected(self):
        run(self.dir, "tips", "--add", "KB-1")
        code, out = run(self.dir, "tips", "--set", "KB-1", "done")
        self.assertEqual(code, 1)


class TestReportArchiveAndSegments(LedgerTestCase):
    """报告全文归档 + 本段边界:周报交叉汇总的两个前提。"""

    def _report(self, name, body):
        p = self.dir / name
        p.write_text(body, encoding="utf-8")
        return str(p)

    def test_report_archived_and_linked(self):
        rec = self.write_session("s.json", {
            "date": "2026-07-20", "session_id": "abcd1234ef", "project": "/x/my-proj",
            "complexity": "M", "active_min": 30, "user_turns": 12, "tokens": {"input": 1},
            "segment": {"from_ts": "2026-07-20T09:00:00Z", "to_ts": "2026-07-20T09:30:00Z",
                        "turns": [1, 12]},
        })
        report = self._report("r.md", "# 复盘报告\n诊断:T1")
        code, out = run(self.dir, "record", "--session-json", rec, "--report", report)
        self.assertEqual(code, 0)
        self.assertEqual(out["report_path"], "reports/2026-07-20-x-my-proj-abcd1234.md")
        archived = self.dir / out["report_path"]
        self.assertTrue(archived.exists())
        self.assertIn("诊断:T1", archived.read_text(encoding="utf-8"))

    def test_second_segment_same_day_does_not_overwrite(self):
        rec = self.write_session("s.json", {
            "date": "2026-07-20", "session_id": "abcd1234ef", "project": "p",
        })
        first = run(self.dir, "record", "--session-json", rec,
                    "--report", self._report("a.md", "第一段"))[1]["report_path"]
        second = run(self.dir, "record", "--session-json", rec,
                     "--report", self._report("b.md", "第二段"))[1]["report_path"]
        self.assertNotEqual(first, second)
        self.assertEqual((self.dir / first).read_text(encoding="utf-8"), "第一段")
        self.assertEqual((self.dir / second).read_text(encoding="utf-8"), "第二段")

    def test_missing_report_warns_but_records(self):
        rec = self.write_session("s.json", {"date": "2026-07-20", "session_id": "x"})
        code, out = run(self.dir, "record", "--session-json", rec)
        self.assertTrue(out["recorded"])
        self.assertIsNone(out["report_path"])
        self.assertTrue(any("没有归档" in w for w in out["warnings"]))

    def test_empty_report_rejected(self):
        rec = self.write_session("s.json", {"date": "2026-07-20", "session_id": "x"})
        code, out = run(self.dir, "record", "--session-json", rec,
                        "--report", self._report("empty.md", "   \n"))
        self.assertEqual(code, 1)
        self.assertIn("error", out)

    def test_last_covered_returns_segment_boundary(self):
        code, out = run(self.dir, "last-covered", "--session-id", "nope")
        self.assertFalse(out["covered"])

        rec = self.write_session("s.json", {
            "date": "2026-07-20", "session_id": "sid1", "project": "p",
            "segment": {"from_ts": "2026-07-20T09:00:00Z",
                        "to_ts": "2026-07-20T09:30:00Z", "turns": [1, 12]},
        })
        run(self.dir, "record", "--session-json", rec,
            "--report", self._report("r.md", "报告一"))
        code, out = run(self.dir, "last-covered", "--session-id", "sid1")
        self.assertTrue(out["covered"])
        self.assertEqual(out["last_to_ts"], "2026-07-20T09:30:00Z")
        self.assertEqual(out["last_turn"], 12)
        self.assertEqual(out["segments"], 1)


class TestWeeklyPack(LedgerTestCase):
    """周报素材:项目对比 + 复发的坑 + 台账 + 报告清单。"""

    def setUp(self):
        super().setUp()
        d = date.today().isoformat()
        for i, (proj, flags, turns, active) in enumerate([
            ("/p/alpha", ["repeated-file-read", "secrets-pasted-in-chat"], 20, 60),
            ("/p/alpha", ["secrets-pasted-in-chat"], 10, 30),
            ("/p/beta", ["oversized-tool-result"], 5, 15),
        ]):
            rec = self.write_session("s%d.json" % i, {
                "date": d, "session_id": "sid%d" % i, "project": proj, "complexity": "M",
                "active_min": active, "user_turns": turns,
                "tokens": {"output": 1000 * (i + 1)},
                "scores": {"overall": 4.0 + i * 0.5},
                "waste_flags": flags,
            })
            p = self.dir / ("r%d.md" % i)
            p.write_text("报告 %d" % i, encoding="utf-8")
            run(self.dir, "record", "--session-json", rec, "--report", str(p))

    def test_project_rollup(self):
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["session_count"], 3)
        alpha = out["by_project"]["/p/alpha"]
        self.assertEqual(alpha["sessions"], 2)
        self.assertEqual(alpha["active_min"], 90)
        self.assertEqual(alpha["user_turns"], 30)
        self.assertEqual(alpha["median_overall"], 4.25)
        self.assertEqual(out["by_project"]["/p/beta"]["sessions"], 1)

    def test_recurring_waste_is_j4_evidence(self):
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        # 只在 2 段里都出现的标记才算复发
        self.assertIn("secrets-pasted-in-chat", out["recurring_waste"])
        self.assertNotIn("repeated-file-read", out["recurring_waste"])
        self.assertNotIn("oversized-tool-result", out["recurring_waste"])

    def test_reports_listed_for_cross_reading(self):
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(len(out["reports_to_read"]), 3)
        self.assertEqual(out["reports_missing"], 0)
        for rel in out["reports_to_read"]:
            self.assertTrue((self.dir / rel).exists())

    def test_ledger_state_included(self):
        run(self.dir, "confirm", "--gap", "T1")
        run(self.dir, "tips", "--add", "KB-01")
        run(self.dir, "tips", "--set", "KB-01", "tried-worked")
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertIn("T1", out["gaps"])
        self.assertEqual(out["practice_rate"], 1.0)

    def test_old_records_excluded(self):
        rec = self.write_session("old.json", {
            "date": "2020-01-01", "session_id": "old", "project": "/p/old",
        })
        run(self.dir, "record", "--session-json", rec)
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["session_count"], 3)
        self.assertNotIn("/p/old", out["by_project"])


class TestTermsAndBaseline(LedgerTestCase):
    def test_terms_cluster_at_three(self):
        run(self.dir, "terms", "--add", "webhook", "--domain", "api-communication")
        run(self.dir, "terms", "--add", "idempotency", "--domain", "api-communication")
        code, out = run(self.dir, "terms", "--clusters")
        self.assertEqual(out["clusters"], {})  # 2 词不聚类

        run(self.dir, "terms", "--add", "rate-limit", "--domain", "api-communication")
        run(self.dir, "terms", "--add", "index", "--domain", "database")
        code, out = run(self.dir, "terms", "--clusters")
        self.assertEqual(
            sorted(out["clusters"]["api-communication"]),
            ["idempotency", "rate-limit", "webhook"],
        )
        self.assertNotIn("database", out["clusters"])

    def test_baseline_needs_ten_records(self):
        rec = {"date": "2026-07-01", "complexity": "M", "duration_min": 10,
               "user_turns": 20, "tokens": {"input": 1000}}
        for i in range(9):
            r = dict(rec, duration_min=10 + i)
            run(self.dir, "record", "--session-json", self.write_session("r%d.json" % i, r))
        code, out = run(self.dir, "baseline", "--complexity", "M")
        self.assertEqual(out, {"ready": False, "count": 9})

        run(self.dir, "record", "--session-json",
            self.write_session("r9.json", dict(rec, duration_min=19)))
        code, out = run(self.dir, "baseline", "--complexity", "M")
        self.assertTrue(out["ready"])
        self.assertEqual(out["count"], 10)
        self.assertEqual(out["medians"]["duration_min"], 14.5)
        self.assertEqual(out["medians"]["user_turns"], 20)
        self.assertEqual(out["medians"]["tokens.input"], 1000)

        # 不同档位互不污染
        code, out = run(self.dir, "baseline", "--complexity", "S")
        self.assertEqual(out, {"ready": False, "count": 0})


if __name__ == "__main__":
    unittest.main()


class TestCompareAgainstBaseline(LedgerTestCase):
    """本次 vs 个人基线。分母只能是你自己同档位的历史,不是任何行业基准。"""

    def _seed(self, n, active_min=40, complexity="M"):
        sess = self.write_session(
            "seed.json",
            {"date": "2026-07-01", "complexity": complexity, "active_min": active_min,
             "user_turns": 10, "tokens": {"input": 1000, "output": 500,
                                          "cache_read": 0, "cache_write": 0},
             "diagnoses": []},
        )
        for _ in range(n):
            run(self.dir, "record", "--session-json", sess)

    def test_refuses_to_compare_without_enough_history(self):
        self._seed(4)
        cur = self.write_session("cur.json", {"active_min": 120, "user_turns": 30})
        code, out = run(self.dir, "compare", "--session-json", cur, "--complexity", "M")
        self.assertEqual(code, 0)
        self.assertFalse(out["ready"])
        self.assertEqual(out["count"], 4)
        # 没有分母时必须明确禁止报告里提"超标"
        self.assertIn("超标", out["note"])

    def test_ratio_and_flagging(self):
        self._seed(10, active_min=40)
        cur = self.write_session(
            "cur.json",
            {"active_min": 80, "user_turns": 10,
             "tokens": {"input": 1000, "output": 500, "cache_read": 0, "cache_write": 0}},
        )
        code, out = run(self.dir, "compare", "--session-json", cur, "--complexity", "M")
        self.assertTrue(out["ready"])
        self.assertEqual(out["baseline_count"], 10)
        self.assertEqual(out["deltas"]["active_min"]["ratio"], 2.0)
        self.assertEqual(out["deltas"]["active_min"]["direction"], "above")
        self.assertIn("active_min", out["flagged"])
        # 持平的指标不该被标记
        self.assertEqual(out["deltas"]["user_turns"]["ratio"], 1.0)
        self.assertNotIn("user_turns", out["flagged"])

    def test_note_forbids_dollar_conversion_and_bare_conclusions(self):
        self._seed(10)
        cur = self.write_session("cur.json", {"active_min": 80})
        _, out = run(self.dir, "compare", "--session-json", cur, "--complexity", "M")
        self.assertIn("prompts[]", out["note"])   # 必须回到逐轮账单找原因
        self.assertIn("美元", out["note"])         # 订阅制下不换算美元


class TestEffectBeforeAfter(LedgerTestCase):
    """建议采纳前后的实测对比——把"这条建议有没有用"变成可证伪的。"""

    def _record(self, name, date_str, active_min):
        sess = self.write_session(
            name,
            {"date": date_str, "complexity": "M", "active_min": active_min,
             "user_turns": 10, "diagnoses": []},
        )
        run(self.dir, "record", "--session-json", sess)

    def test_missing_tip_errors(self):
        code, out = run(self.dir, "effect", "--tip", "KB-99")
        self.assertEqual(code, 1)
        self.assertIn("KB-99", out["error"])

    def test_measures_change_around_adoption_date(self):
        for i, m in enumerate((60, 62, 58)):
            self._record("b%d.json" % i, "2026-07-0%d" % (i + 1), m)
        run(self.dir, "tips", "--add", "KB-24", "--note", "读大文件后清理上下文")
        # 采纳日期就是今天;之后的记录必须晚于它
        pivot = date.today().isoformat()
        for i, m in enumerate((40, 42, 38)):
            self._record("a%d.json" % i, pivot, m)

        code, out = run(self.dir, "effect", "--tip", "KB-24", "--complexity", "M")
        self.assertEqual(code, 0)
        self.assertEqual(out["before"]["n"], 3)
        self.assertEqual(out["after"]["n"], 3)
        self.assertEqual(out["changes"]["active_min"]["before"], 60)
        self.assertEqual(out["changes"]["active_min"]["after"], 40)
        self.assertAlmostEqual(out["changes"]["active_min"]["delta_pct"], -33.3, places=1)
        self.assertTrue(out["reliable"])
        self.assertEqual(out["note"], "读大文件后清理上下文")

    def test_small_sample_is_marked_unreliable(self):
        self._record("b.json", "2026-07-01", 60)
        run(self.dir, "tips", "--add", "KB-24")
        self._record("a.json", date.today().isoformat(), 40)
        _, out = run(self.dir, "effect", "--tip", "KB-24")
        self.assertFalse(out["reliable"])
        self.assertIn("不能说", out["caveat"])


class TestCoverage(LedgerTestCase):
    """复盘覆盖率:忘了复盘的会话必须现形,不能默认当成 100%。"""

    def _index(self, entries):
        p = self.dir / "session-index.jsonl"
        p.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
            encoding="utf-8",
        )

    def test_unavailable_without_hook(self):
        code, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(code, 0)
        self.assertFalse(out["coverage"]["available"])

    def test_counts_sessions_never_retroed(self):
        ts = date.today().isoformat() + "T10:00:00+00:00"
        self._index([
            {"session_id": "s1", "project": "/a", "ts": ts},
            {"session_id": "s2", "project": "/b", "ts": ts},
            {"session_id": "s3", "project": "/c", "ts": ts},
        ])
        sess = self.write_session(
            "r.json",
            {"date": date.today().isoformat(), "session_id": "s1",
             "project": "/a", "complexity": "M", "diagnoses": []},
        )
        run(self.dir, "record", "--session-json", sess)

        _, out = run(self.dir, "weekly-pack", "--days", "7")
        cov = out["coverage"]
        self.assertTrue(cov["available"])
        self.assertEqual(cov["sessions_seen"], 3)
        self.assertEqual(cov["sessions_retroed"], 1)
        self.assertEqual({m["session_id"] for m in cov["not_retroed"]}, {"s2", "s3"})

    def test_old_index_entries_excluded(self):
        self._index([{"session_id": "old", "project": "/a", "ts": "2020-01-01T00:00:00+00:00"}])
        _, out = run(self.dir, "weekly-pack", "--days", "7")
        self.assertEqual(out["coverage"]["sessions_seen"], 0)


class TestSessionEndHook(unittest.TestCase):
    """钩子只登记一行,且任何情况下都不能吵。"""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, stdin_text):
        import subprocess
        hook = Path(__file__).resolve().parent.parent / "hooks" / "session_end_index.py"
        env = dict(os.environ, VIBECODING_RETRO_HOME=str(self.dir))
        return subprocess.run(
            [sys.executable, str(hook)], input=stdin_text, capture_output=True,
            text=True, env=env,
        )

    def test_appends_pointer_line(self):
        r = self._run(json.dumps({"session_id": "abc", "cwd": "/proj",
                                  "transcript_path": "/log.jsonl"}))
        self.assertEqual(r.returncode, 0)
        lines = (self.dir / "session-index.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["session_id"], "abc")
        self.assertEqual(entry["project"], "/proj")

    def test_garbage_input_is_silent(self):
        r = self._run("not json at all")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stderr, "")
        self.assertFalse((self.dir / "session-index.jsonl").exists())

    def test_missing_session_id_writes_nothing(self):
        r = self._run(json.dumps({"cwd": "/proj"}))
        self.assertEqual(r.returncode, 0)
        self.assertFalse((self.dir / "session-index.jsonl").exists())
