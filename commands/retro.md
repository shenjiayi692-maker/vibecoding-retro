---
description: 复盘本段对话:哪里浪费了、为什么、怎么改。报告自动归档
argument-hint: "[会话日志路径|整个会话]"
---

用 **vibecoding-retro** skill 复盘本段对话,按它的流程走完,不要跳步。

用户补充:$ARGUMENTS

- 无参数 → 只复盘**本段增量**(先跑 `ledger.py last-covered` 拿边界)
- 参数含"整个会话"/"全部" → 全量,不加 `--since`
- 参数是一个路径 → 用 `--file <路径>` 解析该日志

**写报告前对一遍 checklist**(在 `templates/report-template.md` 里):

- 通篇不许出现字母编号、档位缩写、分类学名词——**说人话**
- 每条 = 现象 + 代价 + 怎么改,三样缺一样就删掉
- 每条能指到具体轮次,最多 3 条
- 估算值带"约",不换算美元

收尾:

```bash
ledger.py suggest --add "<人话建议>" --check "<下次看什么>" --session-id <id>
ledger.py record --session-json <记录.json> --report <报告.md>
```

**漏了 `--report`,这一段在周报里就只剩几个数字。**
