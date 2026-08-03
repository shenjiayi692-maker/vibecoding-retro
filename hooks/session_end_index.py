#!/usr/bin/env python3
"""SessionEnd 钩子:只登记"这段会话存在过",不做任何分析。

为什么只做这么少:

"对话结束"在 Claude Code 里不是个干净的概念——一个 session 可以跨天、可以 resume,
SessionEnd 触发一次不代表用户说完了。所以这里**不生成报告、不弹通知、不调模型**,
复盘仍然由用户主动说"复盘"发起(那是产品的设计,不是限制)。

它补的是唯一一个真实漏洞:**忘了复盘的会话是隐形的**。
登记之后,周报能算出"本周 7 段会话只复盘了 2 段",汇进已有的周五流程,
不新增一个骚扰用户的通道。

失败必须静默:钩子出错不该影响用户的会话。
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def home():
    override = os.environ.get("VIBECODING_RETRO_HOME")
    return Path(override) if override else Path.home() / ".claude" / "vibecoding-retro"


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}

    session_id = payload.get("session_id") or payload.get("sessionId")
    if not session_id:
        return 0  # 认不出会话就什么都不记,别写垃圾进档案

    entry = {
        "session_id": session_id,
        "project": payload.get("cwd"),
        "transcript": payload.get("transcript_path"),
        "reason": payload.get("reason"),
        "ts": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        base = home()
        base.mkdir(parents=True, exist_ok=True)
        with (base / "session-index.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        return 0  # 静默失败:钩子不该拖累用户的会话
    return 0


if __name__ == "__main__":
    sys.exit(main())
