---
name: vibecoding-retro
description: 复盘一段和 AI 的编程对话:看这次的提问方式、思路和工具使用有没有值得改的地方,以少花 token、少走弯路为导向,用大白话指出问题并给出改法。每次的报告存进本地档案,每周可以做一次汇总看哪些问题在反复出现。当用户说"复盘"、"retro"、"复盘这次 session"、"这次哪里可以优化"、"评估一下刚才的过程"、"session review"、"周复盘"、"周报"时,务必使用本 skill。Claude Code 里自动解析会话日志,其他环境走问卷。
---

# 对话复盘

**这个 skill 只做一件事**:看完一段对话,告诉用户**哪里浪费了、为什么、怎么改**。

判断该不该写进报告,只有一个标准:**这条能不能让下一次对话更省、更快、更少走弯路。**

## 三条不能破的规矩

### 1. 说人话

**报告里不许出现任何内部代号。** 没有字母编号、没有档位缩写、没有分类学名词。

| ❌ 不要写 | ✅ 要写 |
|---|---|
| 「T1 问题定义缺口」 | 「你的核心要求到第 17 轮才第一次说出口」 |
| 「这是 L 档任务」 | 「这种规模的活」 |
| 「建议 KB-24」 | 「把这两个文件的职责写进 CLAUDE.md」 |
| 「委托校准 4 分」 | (不写,除非能说出具体是哪件事分工反了) |
| 「命中 context-bloat 模式」 | 「一个会话装了 7 件不相关的事」 |

用户是来知道自己该怎么改的,不是来学这个工具的分类体系的。

### 2. 每条都要:现象 → 代价 → 怎么改

三样缺一样就别写。**说不出代价的观察,说明它不重要;给不出改法的批评,只是抱怨。**

代价优先用数字(逐轮账单算得出来的),数字算不出来就说清具体后果(比如"压缩之后我把你另一个项目的资料记混了")。

### 3. 最多 3 条,证据必须指到具体轮次

一次说十个问题等于一个都没说。指不到"第几轮、哪句话"的,不写。

**说行为,不说人。** 写"这个习惯让你多花了 910 万 token",不写"你缺乏范围控制能力"。禁止心理分析式措辞。

---

## 流程

### 第一步:拿数据

在 Claude Code 里 → 自动;用户提到 Cursor、Claude.ai、其他 IDE → 问卷。

```bash
python3 scripts/parse_session.py --latest    # candidates 里有前 5 个候选,不对就 --file <路径> 重跑
```

同一个会话可能被复盘过多次(一个 session 常横跨数天)。先查上次覆盖到哪,只看本段增量:

```bash
python3 scripts/ledger.py last-covered --session-id <id>
python3 scripts/parse_session.py --file <日志> --since <last_to_ts>   # covered:true 时
```

例外:用户说"复盘整个会话",或需要看完整弧线(比如判断有没有在细节里死磕)时用全量。

**必须用起来的字段**(详见 `references/waste-patterns.md`):

- `prompts[]` 逐轮账单——**这是证据的骨架**。每个 prompt 花了几次请求、调了什么工具、烧了多少 token、上下文涨了多少
- `metric_confidence`——`estimated` 的数字必须带"约"
- `schema_health.degraded`——非空要在报告里说明哪部分数据不可靠
- `secret_leaks`——单独提醒,不占问题名额,绝不复述密钥字符
- `carry_cost` / `compact_events` / `active_min` / `effort_distribution`

`warnings` 非空如实转告。脚本失败降级:`npx ccusage@latest session --json`;再不行让用户跑 `/cost` 贴过来。

**问卷路径**(其他环境):最多 6 问——工具和模型、时长与轮次、任务一句话、token 数据(没有就 null)、**首条 prompt 原文(必需)**、最大卡点。证据不足的就不说。

### 第二步:找问题

先看机械可测的(`references/waste-patterns.md`):重复读文件、超大工具结果、上下文拖拽、缓存命中率、压缩次数。

再看提问方式和思路(`references/observation-patterns.md`):规格来得太晚、前提没说出口、一个会话装太多事、死磕、人机分工错位、不看改动就继续……

**跨会话的复发问题必须真跑 diff,不能凭印象**:

```bash
python3 scripts/trend_report.py --last 10
```

`waste_flag_counts` 和本次的问题逐项比对,重合才说,并注明"这是第 N 次出现"。没重合就不提。

**和个人历史比**(可选,前十几次都会是 `ready:false`,那是正常的):

```bash
python3 scripts/ledger.py compare --session-json <解析结果.json> --scale medium
```

`ready:false` 就跳过,**不要提"超标",也不要解释为什么没有基线**。

### 第三步:上次的建议兑现了吗

```bash
python3 scripts/ledger.py suggestions --days 30
```

给过的建议里,这次能验证的就验证一下,用一句话说结论。**能给数就给数**:

```bash
python3 scripts/ledger.py effect --since 2026-08-04 --scale medium
```

`reliable:false` 时只能说"前后有变化",不能说"是那次改动带来的"。

**不要追问用户有没有照做。** 没做就没做,提一次就够,不要制造愧疚——这个工具的价值在于每次都给出有用的东西,不在于催人交作业。

### 第四步:写报告

按 `templates/report-template.md`。写完自查一遍:

- [ ] 有没有出现字母编号、档位缩写、分类学名词?有就改成人话
- [ ] 每条是不是都有"现象 → 代价 → 怎么改"三段?
- [ ] 每条能不能指到具体轮次?
- [ ] 是不是 ≤3 条?
- [ ] 估算值有没有带"约"?有没有把 token 换算成美元?(不许)

改法从 `references/playbook.md` 里找,**但不要照抄条目原文**。每条建议要:

1. **绑到用户这次的具体东西上**——指名哪个文件、哪句话、哪个习惯,而不是"建议建立文档习惯"
2. **是今天能做完的一个动作**,不是一套方法论
3. **自带验证方式**——下次看什么数据判断它生效了

### 第五步:入档

```bash
# 给过的建议记一笔(纯追加,没有状态,不用回来更新)
python3 scripts/ledger.py suggest --add "<人话建议>" --check "<下次看什么>" --session-id <id>

# 报告全文 + 指标记录一起入档
python3 scripts/ledger.py record --session-json <记录.json> --report <报告.md>
```

**报告全文必须归档,这是周报唯一的素材来源。** 漏了 `--report`,这段在周报里就只剩几个数字。

记录按 `templates/session-record.json` 写。`session_id`、`project`、`segment` 三个字段决定下次能不能正确算增量,不要省。

---

## 周报(用户说"周复盘""周报")

**周报回答单次答不了的问题**:这周精力实际花在哪、同一个问题在几个项目里重现、有没有在变好。

```bash
python3 scripts/ledger.py weekly-pack --days 7
```

数据包里:`sessions`、`by_project`、`recurring_waste`(≥2 段出现的问题)、`recent_suggestions`、`reports_to_read`、`reports_missing`、`coverage`。

**然后必须逐个读 `reports_to_read` 里的报告全文。** 数字只说明发生了什么,报告里才有当时的证据。跳过这步写出来的周报和单次报告没区别,那是这个功能唯一的失败方式。

按 `templates/weekly-report.md` 输出,写完归档:

```bash
python3 scripts/ledger.py record --session-json <周报记录.json> --report <weekly.md>
```

周报记录的 `env` 记 `weekly`、`scale` 留 null,免得污染基线。

**周报三条规矩**:最多 2 个问题且优先选跨会话反复出现的;**下周只给一件事**;`reports_missing` 和 `coverage.not_retroed` 如实说,不假装素材完整。`coverage` 只陈述不催促——用户有权只复盘他在意的那几段。

### 批量补录

用户说"复盘今天所有 session"或首次回溯时:`parse_session.py --list --days N` 拿候选 → 逐个解析出报告归档 → 再跑 `weekly-pack` 汇总。

首次使用且档案为空时,可以问一句要不要扫最近 30 天——跨会话才看得见反复踩的坑。用户不要就正常单次复盘,**不要留空段落,也不要解释"档案攒够多少条才有 XX 功能"**。

---

## 边界

- 只做统计和模式分析,**绝不**把代码内容、密钥、敏感路径写进报告或档案
- `user_messages` 里的 `«已隐去:…»` 是脚本做的脱敏,**原样保留,不要还原也不要猜**
- **不要给用户提这个工具范围之外的建议。** 比如"去给你另一个项目写份产品定义文档"——那是产品管理辅导,不是对话效率审查。看到自己在写这类建议就删掉
- **不要把某一次复盘的结论写进 skill 自己的文件。** 那是用户的个人数据,属于 `~/.claude/vibecoding-retro/`,不属于要发给所有人的产品
- 数字分三级(见 `metric_confidence`):`exact` 直说、`derived` 说口径、`estimated` 带"约"。**任何情况下不换算成美元**
- 诊断的是行为,不是人格;禁止心理分析式措辞
- 往 `playbook.md` 加条目一律先给 diff、经用户确认
- 报告语言跟随用户
