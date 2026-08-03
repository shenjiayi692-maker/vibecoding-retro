#!/usr/bin/env python3
"""解析 Claude Code 会话 JSONL 日志,输出聚合指标 JSON 到 stdout。

仅标准库,零依赖。流式逐行解析,不整读文件。
绝不输出代码内容/密钥:工具结果只计长度,不保留正文;仅保留真人用户消息全文(诊断证据)。
密钥扫描只报"第几轮、什么来源、什么类型、多长",不回显任何密钥字符。

三件事需要调用方(SKILL.md)注意:

1. `metric_confidence` 给每个指标标了 exact / derived / estimated。
   estimated 的数字在报告里必须带"约",且不能作为唯一证据支撑一条诊断。
2. `prompts` 是逐轮账单:每个用户 prompt 花了多少请求、工具、token、上下文增长。
   诊断引用证据时用它,才能说清"第几轮那句话导致了什么",而不是笼统说"这次浪费多"。
3. `schema_health` 是本解析器对 Claude Code 日志格式的自检。
   本产品读的是**未公开承诺的内部日志格式**,官方改字段不会通知。
   degraded 非空时,报告必须说明哪部分数据不可靠——静默出错的报告比没有报告更糟。

用法:
    python3 parse_session.py --file <path.jsonl>
    python3 parse_session.py --latest        # 自动找 ~/.claude/projects 最近修改的日志
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 浪费模式阈值(按个人节奏可直接改数字)
REPEATED_READ_THRESHOLD = 3      # 同一文件被 Read ≥N 次视为重复读取
OVERSIZED_EST_TOKENS = 10000     # 单个工具结果粗估 token ≥N 视为超大
ACTIVE_GAP_MAX_MIN = 30          # 相邻消息间隔超过 N 分钟视为挂机,不计入活跃时长

# 解析器验证过的 Claude Code 主版本前缀。日志里出现别的版本要报警:
# 本产品读的是内部格式,升级可能静默改字段,而错数字比没数字更危险。
PARSER_TESTED_VERSIONS = ("2.0", "2.1")

# 指标可信度分级。报告措辞的硬依据,别在这里含糊。
#   exact     — 来自 API usage 或直接计数,可当事实陈述
#   derived   — 由精确值按明确规则推算,可陈述但要说明口径
#   estimated — 含拍脑袋的换算或假设,误差可达数倍,必须带"约"
METRIC_CONFIDENCE = {
    "tokens.*": "exact",
    "user_turns": "exact",
    "compact_events": "exact",
    "duration_min": "exact",
    "models": "exact",
    "tool_stats.calls_by_tool": "exact",
    "tool_stats.repeated_file_reads": "exact",
    "prompts[].requests": "exact",
    "prompts[].tokens.*": "exact",
    "prompts[].billed_input": "exact",
    "prompts[].cum_billed_input": "exact",
    "active_min": "derived",
    "tool_stats.cache_hit_rate": "derived",
    "prompts[].context_end": "derived",
    "prompts[].context_growth": "derived",
    "tool_stats.oversized_tool_results[].est_tokens": "estimated",
    "carry_cost[].carried_tokens": "estimated",
}

# 这些前缀的 user 消息是命令/系统注入,不是真人输入
META_PREFIXES = (
    "<command-name>",
    "<local-command",
    "<system-reminder",
    "<bash-input",
    "Caveat: The messages below",
    "[Request interrupted",
    "This session is being continued from a previous conversation",
)

# 密钥扫描:纯前缀/结构匹配,不做语义判断。
# 输出绝不含密钥字符,只报来源、类型、轮次、长度。
SECRET_PATTERNS = (
    ("anthropic-api-key", re.compile(r"sk-ant-api\d{2}-[A-Za-z0-9_\-]{20,}")),
    ("anthropic-oauth-token", re.compile(r"sk-ant-oat\d{2}-[A-Za-z0-9_\-]{20,}")),
    ("openai-api-key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    # re_ 是个三字符前缀,在英文标识符里太常见(refuses_to_…、require_…)。
    # 要求尾部含大写或数字:真密钥是高熵串,snake_case 标识符全是小写加下划线。
    ("resend-api-key", re.compile(r"re_(?=[A-Za-z0-9_\-]*[A-Z0-9])[A-Za-z0-9_\-]{16,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("telegram-bot-token", re.compile(r"\d{8,12}:AA[A-Za-z0-9_\-]{30,}")),
    ("google-api-key", re.compile(r"AIza[A-Za-z0-9_\-]{35}")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)

# 无前缀的裸密钥(如各家 dashboard 直接给的 hex 串)只能靠"短消息里塞了个高熵长串"识别。
# 带连字符的 UUID 和句子里的 git SHA 不会命中,避免误报。
BLOB_RE = re.compile(r"(?<![A-Za-z0-9_\-])[A-Za-z0-9]{32,}(?![A-Za-z0-9_\-])")
BLOB_MAX_MSG_LEN = 300     # 只在短消息里判定
BLOB_MIN_RATIO = 0.4       # 长串占消息比例超过此值才算
# 提到 commit/哈希 的消息里,长 hex 串多半是 git SHA 而非密钥。
# 只抑制模糊桶(high-entropy-blob),带前缀的确诊密钥永远照报。
BLOB_CONTEXT_DENY = re.compile(
    r"commit|提交|revert|回退|rollback|sha|hash|哈希|branch|分支|checkout|merge|rebase|cherry-pick",
    re.IGNORECASE,
)


def scan_secrets(text, turn, source="user-message"):
    """返回 [{turn, source, kind, length, confidence}],绝不返回密钥本身。

    source 取值:
      user-message      — 你自己贴进对话的(最该轮换的就是这些)
      assistant-thinking / assistant-text — 助手复述回去的。
        Claude Code 把 thinking 正文明文写进本地 JSONL,所以助手复述过的密钥
        同样落盘了。只扫确诊前缀,不在助手侧跑高熵启发式(正常长文会误报)。
    """
    return _scan(text, turn, source)[0]


def _scan(text, turn, source):
    """内部实现:返回 (findings, spans)。spans 供 redact 用,绝不出现在输出里。"""
    found = []
    spans = []
    for kind, pattern in SECRET_PATTERNS:
        for m in pattern.finditer(text):
            spans.append((m.start(), m.end(), kind, len(m.group(0))))
            found.append(
                {
                    "turn": turn,
                    "source": source,
                    "kind": kind,
                    "length": len(m.group(0)),
                    "confidence": "confirmed",
                }
            )
    if source != "user-message":
        return found, spans
    if len(text) <= BLOB_MAX_MSG_LEN and not BLOB_CONTEXT_DENY.search(text):
        for m in BLOB_RE.finditer(text):
            if any(s <= m.start() and m.end() <= e for s, e, _k, _l in spans):
                continue  # 已被上面的具体规则覆盖
            if len(m.group(0)) / len(text) >= BLOB_MIN_RATIO:
                spans.append((m.start(), m.end(), "high-entropy-blob", len(m.group(0))))
                found.append(
                    {
                        "turn": turn,
                        "source": source,
                        "kind": "high-entropy-blob",
                        "length": len(m.group(0)),
                        "confidence": "suspected",
                    }
                )
    return found, spans


def redact(text, spans):
    """把命中的密钥替换成占位标记。

    user_messages 全文是诊断证据,必须保留;但密钥不能跟着一起被回显出去——
    本脚本的输出会被写进报告、存进档案、可能被转发,任何一环都不该再出现密钥字符。
    保留标记而不是整段删除,是为了让诊断仍看得出"这一轮你在贴配置"。
    """
    if not spans:
        return text
    merged = []
    for start, end, kind, length in sorted(spans):
        if merged and start <= merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2], prev[3])
        else:
            merged.append((start, end, kind, length))
    out, cursor = [], 0
    for start, end, kind, length in merged:
        out.append(text[cursor:start])
        out.append("«已隐去:%s,%d 字符»" % (kind, length))
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


PROJECTS_DIR = Path.home() / ".claude" / "projects"


def parse_ts(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_meta_text(text):
    stripped = text.lstrip()
    return any(stripped.startswith(p) for p in META_PREFIXES)


def split_user_content(content):
    """拆 user 消息 content → (真人文本或 None, [工具结果文本长度])。

    tool_result 也挂在 user role 下;含 tool_result 块的记录视为工具结果载体。
    """
    if isinstance(content, str):
        return (None, []) if is_meta_text(content) else (content, [])
    if not isinstance(content, list):
        return None, []
    result_lens, text_parts, has_tool_result = [], [], False
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_result":
            has_tool_result = True
            inner = block.get("content")
            if isinstance(inner, str):
                result_lens.append(len(inner))
            elif isinstance(inner, list):
                total = sum(
                    len(b.get("text", ""))
                    for b in inner
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                result_lens.append(total)
        elif btype == "text":
            text_parts.append(block.get("text", ""))
    if has_tool_result:
        return None, result_lens
    text = "\n".join(t for t in text_parts if t).strip()
    if not text or is_meta_text(text):
        return None, []
    return text, []


def _new_prompt(turn, prompt_id, ts, chars):
    return {
        "turn": turn,
        "prompt_id": prompt_id,
        "ts": ts,
        "chars": chars,
        "requests": 0,
        "tools": {},
        "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
        "billed_input": 0,
        "cum_billed_input": 0,
        "context_end": None,
        "context_growth": None,
        "effort": {},
        "skills": {},
        "oversized_results": [],
    }


def parse_session(path, since=None):
    """since 非空(ISO 时间戳)时只统计该时刻之后的记录——用于"本段对话"的增量复盘。"""
    path = Path(path)
    since_ts = parse_ts(since) if since else None
    warnings = []
    if since and since_ts is None:
        warnings.append("--since 时间戳无法解析,已忽略,按全量统计")
    session_id = None
    project = None
    start_ts = end_ts = None
    models = {}
    tokens = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    user_turn = 0
    user_messages = []
    calls_by_tool = {}
    read_counts = {}
    oversized = []
    trend_by_turn = {}
    seen_msg_ids = set()
    bad_lines = 0
    assistant_missing_usage = 0
    compact_events = 0
    model_fallbacks = []
    secret_leaks = []
    seen_leak_keys = set()
    prev_ts = None
    active_seconds = 0.0
    skipped_before_since = 0

    # 逐轮账单
    prompts = []
    current = None
    cum_billed = 0
    prev_context = None
    # 上下文拖拽:大块内容进来后,还被后续多少次请求反复携带
    request_index = 0
    compact_at_requests = []
    carry_origins = []
    effort_totals = {}
    skills_used = {}
    # schema 自检
    versions = set()
    field_seen = {
        "promptId": False,
        "usage": False,
        "effort": False,
        "attributionSkill": False,
        "isCompactSummary": False,
    }
    saw_assistant = False

    def close_prompt():
        if current is not None:
            current["cum_billed_input"] = cum_billed
            prompts.append(current)

    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                bad_lines += 1
                continue
            if not isinstance(rec, dict):
                bad_lines += 1
                continue

            session_id = session_id or rec.get("sessionId")
            project = project or rec.get("cwd")
            if isinstance(rec.get("version"), str):
                versions.add(rec["version"])
            rtype = rec.get("type")
            ts = parse_ts(rec.get("timestamp"))
            # 增量模式:本段之前的记录只用于取 session/project 元信息,不进任何统计
            if since_ts is not None and ts is not None and ts <= since_ts:
                skipped_before_since += 1
                continue
            if ts and rtype in ("user", "assistant"):
                if start_ts is None or ts < start_ts:
                    start_ts = ts
                if end_ts is None or ts > end_ts:
                    end_ts = ts
                # 活跃时长:只累加"还在干活"的间隔,跳过挂机与跨天
                if prev_ts is not None and ts > prev_ts:
                    delta = (ts - prev_ts).total_seconds()
                    if delta <= ACTIVE_GAP_MAX_MIN * 60:
                        active_seconds += delta
                if prev_ts is None or ts > prev_ts:
                    prev_ts = ts

            # 模型安全回退:换上的模型不是用户选的,评分时不能按它判档位
            if rtype == "system" and rec.get("subtype") == "model_refusal_fallback":
                model_fallbacks.append(
                    {
                        "from": rec.get("originalModel"),
                        "to": rec.get("fallbackModel"),
                        "trigger": rec.get("trigger"),
                        "ts": rec.get("timestamp"),
                    }
                )
                continue

            message = rec.get("message")
            if not isinstance(message, dict):
                continue

            if rtype == "user":
                if rec.get("promptId"):
                    field_seen["promptId"] = True
                text, result_lens = split_user_content(message.get("content"))
                for rlen in result_lens:
                    est = rlen // 4
                    if est >= OVERSIZED_EST_TOKENS:
                        oversized.append({"turn": user_turn, "est_tokens": est})
                        if current is not None:
                            current["oversized_results"].append(est)
                        carry_origins.append(
                            {
                                "origin_turn": user_turn,
                                "kind": "oversized_tool_result",
                                "est_tokens": est,
                                "at_request": request_index,
                            }
                        )
                # 上下文压缩摘要是系统生成的,既不是真人轮次,也不能当诊断证据
                if rec.get("isCompactSummary"):
                    field_seen["isCompactSummary"] = True
                    compact_events += 1
                    compact_at_requests.append(request_index)
                    continue
                if rec.get("isSidechain") or rec.get("isMeta") or rec.get("isVisibleInTranscriptOnly"):
                    continue  # 子代理/元消息/仅在 transcript 可见的消息不算真人轮次
                if text is not None:
                    close_prompt()
                    user_turn += 1
                    leaks, spans = _scan(text, user_turn, "user-message")
                    user_messages.append(
                        {
                            "turn": user_turn,
                            "text": redact(text, spans),  # 全文进报告,密钥不进
                            "ts": rec.get("timestamp"),
                        }
                    )
                    for leak in leaks:
                        key = (leak["turn"], leak["kind"], leak["length"])
                        if key in seen_leak_keys:
                            continue
                        seen_leak_keys.add(key)
                        secret_leaks.append(leak)
                    current = _new_prompt(
                        user_turn, rec.get("promptId"), rec.get("timestamp"), len(text)
                    )
                    # 上一轮结束时的上下文规模。取上一轮最后一次请求(不是最大值),
                    # 否则压缩后的负增长会算错。压缩造成的负值是真实信号,保留。
                    prev_context = prompts[-1]["context_end"] if prompts else None

            elif rtype == "assistant":
                saw_assistant = True
                content = message.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_use":
                            name = block.get("name") or "unknown"
                            calls_by_tool[name] = calls_by_tool.get(name, 0) + 1
                            if current is not None:
                                current["tools"][name] = current["tools"].get(name, 0) + 1
                            if name == "Read":
                                fp = (block.get("input") or {}).get("file_path")
                                if fp:
                                    read_counts[fp] = read_counts.get(fp, 0) + 1
                        elif btype in ("thinking", "text"):
                            # thinking 正文明文落盘,助手复述过的密钥同样泄漏了
                            src = "assistant-thinking" if btype == "thinking" else "assistant-text"
                            body = block.get("thinking" if btype == "thinking" else "text") or ""
                            for leak in scan_secrets(body, user_turn, source=src):
                                key = (leak["turn"], leak["kind"], leak["length"])
                                if key in seen_leak_keys:
                                    continue  # 同一轮同长度同类型:是回声不是新泄漏
                                seen_leak_keys.add(key)
                                secret_leaks.append(leak)
                # 同一 API 消息会因流式写盘拆成多行(同 message.id),usage 只计一次
                msg_id = message.get("id")
                if msg_id and msg_id in seen_msg_ids:
                    continue
                if msg_id:
                    seen_msg_ids.add(msg_id)
                eff = rec.get("effort")
                if isinstance(eff, str):
                    field_seen["effort"] = True
                    effort_totals[eff] = effort_totals.get(eff, 0) + 1
                    if current is not None:
                        current["effort"][eff] = current["effort"].get(eff, 0) + 1
                skill = rec.get("attributionSkill")
                if isinstance(skill, str):
                    field_seen["attributionSkill"] = True
                    skills_used[skill] = skills_used.get(skill, 0) + 1
                    if current is not None:
                        current["skills"][skill] = current["skills"].get(skill, 0) + 1
                model = message.get("model")
                if model and model != "<synthetic>":  # <synthetic> 是本地生成的消息,不是模型选择
                    models.setdefault(model, {"messages": 0})["messages"] += 1
                usage = message.get("usage")
                if not isinstance(usage, dict):
                    assistant_missing_usage += 1
                    continue
                field_seen["usage"] = True
                request_index += 1
                inp = usage.get("input_tokens") or 0
                out = usage.get("output_tokens") or 0
                cread = usage.get("cache_read_input_tokens") or 0
                cwrite = usage.get("cache_creation_input_tokens") or 0
                tokens["input"] += inp
                tokens["output"] += out
                tokens["cache_read"] += cread
                tokens["cache_write"] += cwrite
                total_in = inp + cread + cwrite
                cum_billed += total_in
                if current is not None:
                    current["requests"] += 1
                    current["tokens"]["input"] += inp
                    current["tokens"]["output"] += out
                    current["tokens"]["cache_read"] += cread
                    current["tokens"]["cache_write"] += cwrite
                    current["billed_input"] += total_in
                    current["context_end"] = total_in
                    if prev_context is not None:
                        current["context_growth"] = total_in - prev_context
                if total_in > trend_by_turn.get(user_turn, -1):
                    trend_by_turn[user_turn] = total_in

    close_prompt()

    # 上下文拖拽:一块内容进来后,到会话结束(或下一次压缩)之间被多少次请求重复携带。
    # 这是 estimated:est_tokens 本身是 len//4 粗估,且缓存读比新写便宜,数量级参考而已。
    carry_cost = []
    for origin in carry_origins:
        end_at = request_index
        for c in compact_at_requests:
            if c >= origin["at_request"]:
                end_at = c
                break
        carried_requests = max(end_at - origin["at_request"], 0)
        if carried_requests <= 0:
            continue
        carry_cost.append(
            {
                "origin_turn": origin["origin_turn"],
                "kind": origin["kind"],
                "est_tokens": origin["est_tokens"],
                "carried_requests": carried_requests,
                "carried_tokens": origin["est_tokens"] * carried_requests,
            }
        )
    carry_cost.sort(key=lambda c: -c["carried_tokens"])

    if bad_lines:
        warnings.append("%d 行无法解析为 JSON,已跳过" % bad_lines)
    if compact_events:
        warnings.append(
            "检测到 %d 次上下文压缩(摘要已排除出真人轮次);压缩本身是上下文膨胀信号" % compact_events
        )
    if model_fallbacks:
        warnings.append(
            "检测到 %d 次模型安全回退,实际使用的模型不完全是用户选择,评分模型档位时须扣除" % len(model_fallbacks)
        )
    if secret_leaks:
        by_src = {}
        for leak in secret_leaks:
            by_src[leak["source"]] = by_src.get(leak["source"], 0) + 1
        warnings.append(
            "⚠️ 检测到 %d 处疑似密钥出现在明文日志中(%s),建议轮换"
            % (len(secret_leaks), "、".join("%s×%d" % (k, v) for k, v in sorted(by_src.items())))
        )
    if assistant_missing_usage:
        warnings.append("%d 条 assistant 消息缺 usage 字段,token 统计不完整" % assistant_missing_usage)
    if session_id is None:
        session_id = path.stem
        warnings.append("日志中无 sessionId 字段,用文件名代替")
    if project is None:
        project = path.parent.name
        warnings.append("日志中无 cwd 字段,用目录名代替")
    if start_ts is None:
        warnings.append("未找到任何有效时间戳")

    # schema 自检:本产品读的是未公开承诺的内部格式,静默失真比崩溃更危险
    degraded = []
    untested = sorted(
        v for v in versions if not any(v.startswith(p + ".") or v == p for p in PARSER_TESTED_VERSIONS)
    )
    if untested:
        degraded.append(
            "日志来自未验证过的 Claude Code 版本 %s(解析器验证过 %s.x),字段可能已变更"
            % (",".join(untested), "/".join(PARSER_TESTED_VERSIONS))
        )
    attribution_mode = "prompt-id" if field_seen["promptId"] else "turn-boundary"
    if saw_assistant and not field_seen["promptId"] and user_turn:
        degraded.append("日志无 promptId 字段,逐轮账单退化为按用户消息边界切分(仍可用,精度略降)")
    if saw_assistant and not field_seen["usage"]:
        degraded.append("日志无 usage 字段,全部 token 数字不可用,不要在报告里引用")
    for d in degraded:
        warnings.append("⚠️ schema 自检:" + d)

    duration_min = None
    if start_ts and end_ts:
        duration_min = round((end_ts - start_ts).total_seconds() / 60, 1)
    active_min = round(active_seconds / 60, 1) if start_ts else None
    # 跨天会话的 duration_min 主要是挂机,提醒调用方别拿它评分
    if duration_min and active_min is not None and duration_min > 2 * max(active_min, 1):
        warnings.append(
            "duration_min(%.1f 分)含大量挂机时间,评分请用 active_min(%.1f 分)" % (duration_min, active_min)
        )

    denom = tokens["input"] + tokens["cache_read"] + tokens["cache_write"]
    cache_hit_rate = round(tokens["cache_read"] / denom, 4) if denom else None

    repeated = [
        {"path": p, "count": c}
        for p, c in sorted(read_counts.items(), key=lambda kv: -kv[1])
        if c >= REPEATED_READ_THRESHOLD
    ]

    if skipped_before_since:
        warnings.append(
            "增量模式:跳过 %d 条本段之前的记录(--since %s)" % (skipped_before_since, since)
        )

    return {
        "session_id": session_id,
        "project": project,
        "since": since if since_ts else None,
        "start": start_ts.isoformat() if start_ts else None,
        "end": end_ts.isoformat() if end_ts else None,
        "duration_min": duration_min,
        "active_min": active_min,
        "models": models,
        "model_fallbacks": model_fallbacks,
        "tokens": tokens,
        "user_turns": user_turn,
        "user_messages": user_messages,
        "compact_events": compact_events,
        "secret_leaks": secret_leaks,
        "prompts": prompts,
        "carry_cost": carry_cost,
        "effort_distribution": effort_totals,
        "skills_used": skills_used,
        "tool_stats": {
            "calls_by_tool": calls_by_tool,
            "repeated_file_reads": repeated,
            "oversized_tool_results": oversized,
            "cache_hit_rate": cache_hit_rate,
        },
        "input_token_trend": [
            {"turn": t, "input_total": v} for t, v in sorted(trend_by_turn.items())
        ],
        "schema_health": {
            "cc_versions": sorted(versions),
            "parser_tested_versions": list(PARSER_TESTED_VERSIONS),
            "attribution_mode": attribution_mode,
            "fields_present": field_seen,
            "degraded": degraded,
        },
        "metric_confidence": METRIC_CONFIDENCE,
        "warnings": warnings,
    }


def find_latest(limit=5, days=None):
    """返回按修改时间倒序的日志候选;days 非空则只要最近 N 天内改动过的。"""
    candidates = []
    cutoff = None
    if days is not None:
        cutoff = datetime.now(tz=timezone.utc).timestamp() - days * 86400
    if PROJECTS_DIR.is_dir():
        for p in PROJECTS_DIR.glob("*/*.jsonl"):
            try:
                st = p.stat()
            except OSError:
                continue
            if cutoff is not None and st.st_mtime < cutoff:
                continue
            candidates.append((st.st_mtime, st.st_size, p))
    candidates.sort(key=lambda x: -x[0])
    return [
        {
            "path": str(p),
            "project": p.parent.name,
            "mtime": datetime.fromtimestamp(m, tz=timezone.utc).isoformat(),
            "size_kb": round(s / 1024, 1),
        }
        for m, s, p in candidates[:limit]
    ]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", help="JSONL 日志路径")
    group.add_argument("--latest", action="store_true", help="解析最近修改的会话日志")
    group.add_argument("--list", action="store_true", help="只列出日志候选,不解析(批量复盘/冷启动回溯用)")
    parser.add_argument("--limit", type=int, default=10, help="--list 返回条数,默认 10")
    parser.add_argument("--days", type=int, help="--list 只要最近 N 天内改动过的")
    parser.add_argument(
        "--since",
        help="只统计该 ISO 时间戳之后的记录(本段对话增量复盘;边界取自 ledger.py last-covered)",
    )
    args = parser.parse_args(argv)

    if args.list:
        found = find_latest(limit=args.limit, days=args.days)
        json.dump({"count": len(found), "sessions": found}, sys.stdout, ensure_ascii=False, indent=2)
        print()
        return 0

    if args.latest:
        candidates = find_latest()
        if not candidates:
            json.dump({"error": "未在 %s 找到任何会话日志" % PROJECTS_DIR}, sys.stdout, ensure_ascii=False)
            print()
            return 1
        result = parse_session(candidates[0]["path"], since=args.since)
        result["source_file"] = candidates[0]["path"]
        result["candidates"] = candidates  # 前 5 供确认;如不是目标会话,用 --file 重跑
    else:
        p = Path(args.file)
        if not p.is_file():
            json.dump({"error": "文件不存在: %s" % p}, sys.stdout, ensure_ascii=False)
            print()
            return 1
        result = parse_session(p, since=args.since)
        result["source_file"] = str(p)

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
