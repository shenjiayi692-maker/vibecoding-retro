---
description: 复盘本段 vibecoding 对话:效率评分、能力缺口诊断、带出处的优化建议,报告自动归档
argument-hint: "[会话日志路径|整个会话]"
---

用 **vibecoding-retro** skill 复盘本段对话,完整按它的《总流程》七步走,不要跳步。

用户补充:$ARGUMENTS

- 无参数 → 默认只复盘**本段增量**(先查 `ledger.py last-covered` 拿边界)
- 参数含"整个会话"/"全部" → 全量复盘,不加 `--since`
- 参数是一个路径 → 用 `--file <路径>` 解析该日志

收尾必须做完这两件事,否则闭环断掉:

1. 问"诊断你认吗?哪些建议列入待实践?",按回答调 `confirm`/`reject`/`tips --add`
2. 把报告全文写进 markdown 文件,用 `record --session-json ... --report ...` 归档——**漏了 `--report`,这一段在周报里就只剩几个数字**
