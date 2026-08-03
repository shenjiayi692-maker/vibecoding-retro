"""parse_session.py 的夹具测试。运行:python -m unittest discover tests"""
import json
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "vibecoding-retro" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import parse_session  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class TestCleanSession(unittest.TestCase):
    """干净会话:无浪费标记,统计数字精确匹配。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "clean_session.jsonl")

    def test_session_meta(self):
        self.assertEqual(self.r["session_id"], "fixture-session-0001")
        self.assertEqual(self.r["project"], "/Users/test/demo-project")
        self.assertEqual(self.r["duration_min"], 22.0)

    def test_tokens_exact_with_dedupe(self):
        # m1 出现两行(流式重复),usage 只计一次
        self.assertEqual(
            self.r["tokens"],
            {"input": 650, "output": 200, "cache_read": 7000, "cache_write": 500},
        )

    def test_models_deduped(self):
        self.assertEqual(self.r["models"], {"claude-sonnet-4-6": {"messages": 4}})

    def test_user_turns_filter_meta_and_sidechain(self):
        # 命令消息、子代理消息、tool_result 都不算真人轮次
        self.assertEqual(self.r["user_turns"], 3)
        texts = [m["text"] for m in self.r["user_messages"]]
        self.assertEqual(len(texts), 3)
        self.assertIn("日志解析器", texts[0])
        self.assertIn("字段缺失", texts[1])
        self.assertIn("收工", texts[2])
        self.assertEqual([m["turn"] for m in self.r["user_messages"]], [1, 2, 3])

    def test_no_waste_flags(self):
        stats = self.r["tool_stats"]
        self.assertEqual(stats["repeated_file_reads"], [])
        self.assertEqual(stats["oversized_tool_results"], [])
        self.assertEqual(stats["calls_by_tool"], {"Read": 3})

    def test_cache_hit_rate(self):
        self.assertEqual(self.r["tool_stats"]["cache_hit_rate"], round(7000 / 8150, 4))

    def test_input_token_trend(self):
        self.assertEqual(
            self.r["input_token_trend"],
            [
                {"turn": 1, "input_total": 2200},
                {"turn": 2, "input_total": 3300},
                {"turn": 3, "input_total": 1050},
            ],
        )

    def test_no_warnings(self):
        self.assertEqual(self.r["warnings"], [])


class TestWastefulSession(unittest.TestCase):
    """浪费会话:同文件读 4 次 + 40k 工具结果都被检出。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "wasteful_session.jsonl")

    def test_repeated_file_reads_detected(self):
        self.assertEqual(
            self.r["tool_stats"]["repeated_file_reads"],
            [{"path": "src/main.py", "count": 4}],
        )

    def test_oversized_tool_result_detected(self):
        oversized = self.r["tool_stats"]["oversized_tool_results"]
        self.assertEqual(len(oversized), 1)
        self.assertEqual(oversized[0]["est_tokens"], 40000)
        self.assertEqual(oversized[0]["turn"], 2)

    def test_tool_calls(self):
        self.assertEqual(self.r["tool_stats"]["calls_by_tool"], {"Read": 4, "Bash": 1})


class TestSchemaDrift(unittest.TestCase):
    """schema 漂移:不崩,warnings 有内容,能解析的照常解析。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "schema_drift.jsonl")

    def test_does_not_crash_and_warns(self):
        self.assertTrue(self.r["warnings"])
        joined = " ".join(self.r["warnings"])
        self.assertIn("无法解析", joined)  # 坏 JSON 行
        self.assertIn("usage", joined)     # 缺 usage 字段

    def test_partial_usage_still_counted(self):
        self.assertEqual(self.r["tokens"]["output"], 80)
        self.assertEqual(self.r["tokens"]["input"], 0)

    def test_user_turns_still_parsed(self):
        self.assertEqual(self.r["user_turns"], 2)
        self.assertIsNotNone(self.r["start"])
        self.assertIsNotNone(self.r["end"])


class TestLeakySession(unittest.TestCase):
    """压缩摘要排除、模型回退标注、密钥扫描三件事。夹具里的密钥均为伪造占位串。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "leaky_session.jsonl")

    def test_compact_summary_excluded_from_turns(self):
        # 7 条真人消息 + 1 条压缩摘要:摘要不计轮次、不进诊断证据
        self.assertEqual(self.r["user_turns"], 7)
        self.assertEqual(self.r["compact_events"], 1)
        for m in self.r["user_messages"]:
            self.assertNotIn("being continued from a previous conversation", m["text"])
        self.assertTrue(any("上下文压缩" in w for w in self.r["warnings"]))

    def test_model_fallback_annotated(self):
        self.assertEqual(
            self.r["model_fallbacks"],
            [{"from": "claude-fable-5", "to": "claude-opus-4-8",
              "trigger": "refusal", "ts": "2026-07-05T09:10:00.000Z"}],
        )
        self.assertTrue(any("模型安全回退" in w for w in self.r["warnings"]))

    def test_synthetic_not_counted_as_model_choice(self):
        self.assertNotIn("<synthetic>", self.r["models"])
        self.assertEqual(
            self.r["models"],
            {"claude-sonnet-4-6": {"messages": 3}, "claude-opus-4-8": {"messages": 1}},
        )

    def test_secrets_detected_by_kind(self):
        leaks = self.r["secret_leaks"]
        self.assertEqual(
            [(l["turn"], l["kind"], l["confidence"]) for l in leaks],
            [
                (2, "anthropic-api-key", "confirmed"),
                (3, "jwt", "confirmed"),
                (4, "high-entropy-blob", "suspected"),
                (7, "anthropic-api-key", "confirmed"),   # 助手 thinking 里复述的
                (7, "github-token", "confirmed"),        # 只在 thinking 里出现过
            ],
        )
        self.assertTrue(any("疑似密钥" in w for w in self.r["warnings"]))

    def test_no_false_positive_on_uuid_and_git_sha(self):
        flagged_turns = {l["turn"] for l in self.r["secret_leaks"]}
        self.assertNotIn(5, flagged_turns)  # 带连字符的 UUID
        self.assertNotIn(6, flagged_turns)  # 句子里的 git SHA

    def test_never_echoes_secret_material(self):
        # 整个输出——包括 user_messages 全文——都不得出现密钥字符。
        # 这里曾经给 user_messages 开过例外,那是个洞:解析结果会进报告、进档案、被转发。
        blob = json.dumps(self.r, ensure_ascii=False)
        for needle in ("sk-ant-", "eyJ", "0000000000"):
            self.assertNotIn(needle, blob)

    def test_redaction_keeps_diagnostic_context(self):
        # 密钥被隐去,但"这一轮你在贴配置"这个诊断信号要留下
        t2 = next(m for m in self.r["user_messages"] if m["turn"] == 2)
        self.assertIn("api key", t2["text"])
        self.assertIn("«已隐去:anthropic-api-key", t2["text"])

    def test_redaction_does_not_touch_clean_turns(self):
        t1 = next(m for m in self.r["user_messages"] if m["turn"] == 1)
        self.assertNotIn("已隐去", t1["text"])


class TestActiveDuration(unittest.TestCase):
    """跨天会话的 duration_min 是挂机跨度,active_min 才是真实投入。"""

    def _write(self, stamps):
        import tempfile

        self._tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for i, ts in enumerate(stamps):
            rec = {
                "type": "user" if i % 2 == 0 else "assistant",
                "timestamp": ts,
                "sessionId": "t",
                "cwd": "/tmp",
                "message": {"role": "user", "content": "第%d条" % i}
                if i % 2 == 0
                else {"id": "m%d" % i, "role": "assistant", "model": "m",
                      "content": [{"type": "text", "text": "ok"}]},
            }
            self._tmp.write(json.dumps(rec) + "\n")
        self._tmp.close()
        return parse_session.parse_session(self._tmp.name)

    def test_idle_gap_excluded(self):
        # 两段各 10 分钟的工作,中间隔了 8 小时挂机
        r = self._write([
            "2026-07-01T09:00:00.000Z",
            "2026-07-01T09:05:00.000Z",
            "2026-07-01T09:10:00.000Z",
            "2026-07-01T17:10:00.000Z",   # 8 小时后回来
            "2026-07-01T17:15:00.000Z",
            "2026-07-01T17:20:00.000Z",
        ])
        self.assertEqual(r["duration_min"], 500.0)   # 跨度
        self.assertEqual(r["active_min"], 20.0)      # 10 + 10
        self.assertTrue(any("挂机" in w for w in r["warnings"]))

    def test_continuous_session_active_equals_span(self):
        r = self._write([
            "2026-07-01T09:00:00.000Z",
            "2026-07-01T09:05:00.000Z",
            "2026-07-01T09:12:00.000Z",
        ])
        self.assertEqual(r["active_min"], 12.0)
        self.assertEqual(r["duration_min"], 12.0)
        self.assertFalse(any("挂机" in w for w in r["warnings"]))


class TestListMode(unittest.TestCase):
    def test_list_outputs_candidates(self):
        import io
        import contextlib

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_session.main(["--list", "--limit", "3"])
        self.assertEqual(code, 0)
        out = json.loads(buf.getvalue())
        self.assertIn("sessions", out)
        self.assertLessEqual(len(out["sessions"]), 3)
        for s in out["sessions"]:
            self.assertIn("project", s)
            self.assertIn("mtime", s)


class TestSecretScanUnit(unittest.TestCase):
    def test_known_prefixes(self):
        cases = {
            # 尾部含大写/数字才算——纯小写下划线串是标识符不是密钥,见 TestSecretPatternPrecision
            "re_" + "x" * 10 + "X" + "9" * 9: "resend-api-key",
            "ghp_" + "y" * 36: "github-token",
            "AKIA" + "A" * 16: "aws-access-key",
            "123456789:AA" + "z" * 33: "telegram-bot-token",
            "-----BEGIN RSA PRIVATE KEY-----": "private-key-block",
        }
        for sample, kind in cases.items():
            found = parse_session.scan_secrets("key: " + sample, 1)
            self.assertTrue(found, "%s 未被检出" % kind)
            self.assertEqual(found[0]["kind"], kind)

    def test_clean_text_no_findings(self):
        self.assertEqual(parse_session.scan_secrets("帮我把登录流程跑通,顺便看下 src/auth.ts", 1), [])

    def test_long_message_blob_not_flagged(self):
        # 长消息里的长串不进模糊桶(避免正文误报),只有短消息才判定
        text = "背景说明:" + "这是一段很长的任务描述。" * 30 + "a" * 40
        self.assertEqual(parse_session.scan_secrets(text, 1), [])


class TestCLI(unittest.TestCase):
    def test_missing_file_returns_error(self):
        import io
        import contextlib
        import json

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = parse_session.main(["--file", "/nonexistent/x.jsonl"])
        self.assertEqual(code, 1)
        self.assertIn("error", json.loads(buf.getvalue()))


if __name__ == "__main__":
    unittest.main()


class TestPromptAttribution(unittest.TestCase):
    """逐轮账单:每个用户 prompt 花了多少请求/工具/token。

    这是诊断证据的骨架——没有它,诊断只能说"这次浪费多",说不出"第几轮那句话造成的"。
    """

    @classmethod
    def setUpClass(cls):
        cls.clean = parse_session.parse_session(FIXTURES / "clean_session.jsonl")
        cls.waste = parse_session.parse_session(FIXTURES / "wasteful_session.jsonl")

    def test_one_prompt_per_human_turn(self):
        self.assertEqual(len(self.clean["prompts"]), self.clean["user_turns"])
        self.assertEqual([p["turn"] for p in self.clean["prompts"]], [1, 2, 3])

    def test_prompt_id_captured(self):
        # 真实日志里 promptId 挂在 user 记录上,是切分的首选键
        self.assertTrue(all(p["prompt_id"] for p in self.clean["prompts"]))

    def test_per_prompt_tokens_sum_to_total(self):
        for key in ("input", "output", "cache_read", "cache_write"):
            self.assertEqual(
                sum(p["tokens"][key] for p in self.clean["prompts"]),
                self.clean["tokens"][key],
                "逐轮 token 之和必须等于总量,否则归因漏了请求",
            )

    def test_cumulative_billed_is_monotonic(self):
        # 报告靠 cum[b] - cum[a] 一次减法算出"某段作废了多少",所以必须单调不减
        cums = [p["cum_billed_input"] for p in self.waste["prompts"]]
        self.assertEqual(cums, sorted(cums))

    def test_tools_attributed_to_owning_turn(self):
        by_turn = {p["turn"]: p["tools"] for p in self.waste["prompts"]}
        merged = {}
        for tools in by_turn.values():
            for name, n in tools.items():
                merged[name] = merged.get(name, 0) + n
        self.assertEqual(merged, self.waste["tool_stats"]["calls_by_tool"])

    def test_effort_distribution(self):
        self.assertEqual(self.clean["effort_distribution"], {"high": 4})


class TestCarryCost(unittest.TestCase):
    """上下文拖拽:大块内容进来后被后续多少次请求反复携带。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "wasteful_session.jsonl")

    def test_oversized_result_is_tracked(self):
        self.assertTrue(self.r["carry_cost"], "埋了 40k 工具结果,应算出拖拽成本")

    def test_carried_tokens_is_product(self):
        for c in self.r["carry_cost"]:
            self.assertEqual(c["carried_tokens"], c["est_tokens"] * c["carried_requests"])
            self.assertGreater(c["carried_requests"], 0)

    def test_sorted_by_impact(self):
        vals = [c["carried_tokens"] for c in self.r["carry_cost"]]
        self.assertEqual(vals, sorted(vals, reverse=True))


class TestMetricConfidence(unittest.TestCase):
    """指标可信度分级:估算值不能冒充精确值。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "clean_session.jsonl")

    def test_confidence_map_present(self):
        mc = self.r["metric_confidence"]
        self.assertEqual(mc["tokens.*"], "exact")
        self.assertEqual(mc["active_min"], "derived")
        self.assertEqual(mc["tool_stats.oversized_tool_results[].est_tokens"], "estimated")

    def test_only_three_levels(self):
        self.assertEqual(
            set(self.r["metric_confidence"].values()), {"exact", "derived", "estimated"}
        )


class TestSchemaHealth(unittest.TestCase):
    """schema 自检:读的是未公开承诺的内部格式,静默失真比崩溃更危险。"""

    def test_clean_session_is_healthy(self):
        r = parse_session.parse_session(FIXTURES / "clean_session.jsonl")
        self.assertEqual(r["schema_health"]["attribution_mode"], "prompt-id")
        self.assertEqual(r["schema_health"]["degraded"], [])
        self.assertEqual(r["schema_health"]["cc_versions"], ["2.1.219"])

    def test_drift_is_reported_not_swallowed(self):
        r = parse_session.parse_session(FIXTURES / "schema_drift.jsonl")
        degraded = r["schema_health"]["degraded"]
        self.assertTrue(degraded)
        joined = " ".join(degraded)
        self.assertIn("9.9.9", joined)          # 未验证过的版本要点名
        self.assertIn("promptId", joined)       # 归因降级要说明
        self.assertEqual(r["schema_health"]["attribution_mode"], "turn-boundary")
        # 降级不等于罢工:能解析的照常解析
        self.assertGreater(r["user_turns"], 0)

    def test_degraded_surfaces_in_warnings(self):
        r = parse_session.parse_session(FIXTURES / "schema_drift.jsonl")
        self.assertTrue(any("schema 自检" in w for w in r["warnings"]))


class TestAssistantSideLeaks(unittest.TestCase):
    """thinking 正文明文落盘,助手复述过的密钥同样泄漏了。"""

    @classmethod
    def setUpClass(cls):
        cls.r = parse_session.parse_session(FIXTURES / "leaky_session.jsonl")

    def test_thinking_leak_detected_with_source(self):
        thinking = [l for l in self.r["secret_leaks"] if l["source"] == "assistant-thinking"]
        self.assertTrue(thinking)
        self.assertIn("github-token", {l["kind"] for l in thinking})

    def test_every_leak_is_tagged(self):
        for leak in self.r["secret_leaks"]:
            self.assertIn(leak["source"], ("user-message", "assistant-thinking", "assistant-text"))

    def test_no_secret_characters_in_output(self):
        blob = json.dumps(self.r, ensure_ascii=False)
        self.assertNotIn("sk-ant-api03-AAAA", blob)
        self.assertNotIn("ghp_BBBB", blob)

    def test_same_turn_echo_is_not_double_counted(self):
        # 同一轮里用户贴的和助手复述的是同一处泄漏,不该算两次
        keys = [(l["turn"], l["kind"], l["length"]) for l in self.r["secret_leaks"]]
        self.assertEqual(len(keys), len(set(keys)))

    def test_warning_breaks_down_by_source(self):
        w = " ".join(self.r["warnings"])
        self.assertIn("assistant-thinking", w)


class TestSecretPatternPrecision(unittest.TestCase):
    """短前缀模式最容易误报,给别人用之后这类噪声会真的发生。"""

    def test_resend_prefix_ignores_snake_case_identifiers(self):
        # re_ 在英文标识符里太常见:refuses_to_…、re_export_… 都不是密钥
        for text in (
            "def test_refuses_to_compare_without_enough_history(self):",
            "re_export_all_the_modules_now",
        ):
            kinds = {f["kind"] for f in parse_session.scan_secrets(text, 1)}
            self.assertNotIn("resend-api-key", kinds, text)

    def test_resend_prefix_still_catches_real_shape(self):
        for text in ("resend key: re_AbC123dEfG456hIjK789", "re_" + "9" * 20):
            kinds = {f["kind"] for f in parse_session.scan_secrets(text, 1)}
            self.assertIn("resend-api-key", kinds, text)
