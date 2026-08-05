#!/usr/bin/env python3
"""读 sessions.jsonl,输出近 N 次会话的指标趋势 JSON(供周报场景)。仅标准库。

不做可视化——趋势的解读和报告撰写由 LLM 完成。

用法:
    python3 trend_report.py [--last 10] [--scale medium] [--dir <档案目录>]
"""
import argparse
import json
import os
import statistics
import sys
from pathlib import Path


def default_dir():
    env = os.environ.get("VIBECODING_RETRO_HOME")
    return Path(env) if env else Path.home() / ".claude" / "vibecoding-retro"


def pick(record, dotted):
    cur = record
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur if isinstance(cur, (int, float)) else None



LEGACY_SCALE = {"S": "small", "M": "medium", "L": "large"}


def ledger_scale(record):
    """取任务规模,兼容旧记录的 complexity: S/M/L。"""
    s = record.get("scale")
    if s in ("small", "medium", "large"):
        return s
    return LEGACY_SCALE.get(record.get("complexity"))


METRICS = (
    "active_min",
    "duration_min",
    "user_turns",
    "correction_turns",
    "tokens.input",
    "tokens.output",
    "tokens.cache_read",
    "tokens.cost_usd",
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--last", type=int, default=10, help="取最近 N 条记录(默认 10)")
    parser.add_argument("--scale", choices=["small", "medium", "large"], help="只看某个规模的任务")
    parser.add_argument("--dir", help="档案目录(默认 ~/.claude/vibecoding-retro)")
    args = parser.parse_args(argv)

    path = (Path(args.dir) if args.dir else default_dir()) / "sessions.jsonl"
    if not path.exists():
        json.dump({"error": "未找到 %s" % path, "count": 0}, sys.stdout, ensure_ascii=False)
        print()
        return 1

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)

    if args.scale:
        records = [r for r in records if ledger_scale(r) == args.scale]
    window = records[-args.last:]

    series = []
    for r in window:
        point = {"date": r.get("date"), "scale": ledger_scale(r)}
        for m in METRICS:
            point[m] = pick(r, m)
        point["waste_flags"] = r.get("waste_flags") or []
        series.append(point)

    summary = {}
    for m in METRICS:
        vals = [p[m] for p in series if p[m] is not None]
        if len(vals) >= 2:
            half = max(1, len(vals) // 2)
            summary[m] = {
                "median": statistics.median(vals),
                "first_half_median": statistics.median(vals[:half]),
                "second_half_median": statistics.median(vals[-half:]),
            }

    flag_counts = {}
    for p in series:
        for flag in p["waste_flags"]:
            flag_counts[flag] = flag_counts.get(flag, 0) + 1

    json.dump(
        {
            "count": len(series),
            "total_records": len(records),
            "scale": args.scale,
            "series": series,
            "summary": summary,
            "waste_flag_counts": flag_counts,
        },
        sys.stdout,
        ensure_ascii=False,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
