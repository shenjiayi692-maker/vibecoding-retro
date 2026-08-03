---
name: vibecoding-retro
description: 服务于高频使用 AI 的产品经理的工作流优化复盘工具。每次 vibecoding 会话后:五维效率评分、思维与技术缺口诊断、从内置知识库(官方文档+建造者实践,带出处分级)给出可执行优化建议并记录待实践点,下次复盘验证实践效果,形成学习闭环。当用户说"复盘"、"retro"、"复盘这次 session"、"这次工作流有什么可优化的"、"评估一下刚才的编码过程"、"session review"时,或说"更新知识库"时,务必使用本 skill。支持 Claude Code(自动解析日志)与 Cursor/Claude.ai(问卷补充)。
---

# Vibecoding Retro:PM 的 AI 工作流优化复盘

**产品定位**:服务已经高频使用 AI 的产品经理,以专业同侪(而非教练)的姿态帮他们持续优化工作流。核心闭环:**发现问题 → 从知识库给出带出处的优化做法 → 记录待实践 → 下次复盘验证有没有用、有没有效**。北极星指标是建议实践率。思维架构诊断(T1–T6)保留:发现基本功层面的缺失时直接点明,不绕弯,但保持同侪口吻。

## 总流程

1. **采集数据**(自动优先,问卷兜底)
2. **读取档案**:`sessions.jsonl`、`gap-ledger.json`、`learnings.md` —— 并取出**上次的待实践清单(tips_to_try)**
3. **验证上次实践**(闭环的关键步骤,先于新诊断)
4. **五维评分**(读 `references/scoring-rubric.md`)
5. **缺口诊断**(读 `references/capability-diagnosis.md`)
6. **知识库匹配**(读 `references/knowledge-base.md`,按索引表把诊断/扣分项映射到具体技巧)
7. **输出报告**,收集反馈,更新档案与待实践清单

另有独立指令:用户说"**更新知识库**"时,跳过复盘流程,直接执行 knowledge-base.md 末尾的《月度更新协议》。复盘时若发现 last_updated 距今 >45 天,提醒一句。

## 第一步:采集数据

当前就在 Claude Code 会话内 → 自动路径;用户提到 Cursor、Claude.ai、其他 IDE → 问卷路径;不确定 → 问一句"这次 session 在哪个工具里做的?"

### 自动路径(Claude Code)

```bash
python3 scripts/parse_session.py --latest    # candidates 字段列出前 5 候选;不是目标会话就 --file <路径> 重跑
```

**同一个会话可能被复盘多次**(一个 session id 常横跨数天、包含多段工作)。拿到 session_id 后先查上次覆盖到哪,只诊断本段增量,否则会把上次已诊断过的内容重复计入台账:

```bash
python3 scripts/ledger.py last-covered --session-id <id>
# covered:true → 用 last_to_ts 重新解析本段
python3 scripts/parse_session.py --file <日志> --since <last_to_ts>
```

例外:用户明确说"复盘整个会话",或需要判断 T5(死磕 >15 轮)这类要看完整弧线的信号时,用全量。

一次拿到:token/模型/时长/轮次、**user_messages 用户消息全文(诊断的证据源,必须通读)**、**prompts 逐轮账单**、浪费模式(重复读取/超大工具结果/缓存命中率/上下文膨胀趋势)。`warnings` 非空时如实转告,缺的维度记 N/A。脚本失败再降级:`npx ccusage@latest session --json`;仍不行则会话内自查,token 数据让用户跑 `/cost` 贴过来。

**这些字段必须用起来,不要只看 token:**

| 字段 | 怎么用 |
|---|---|
| `prompts[]` | **逐轮账单**:每个用户 prompt 花了几次请求、调了什么工具、烧了多少 token、上下文涨了多少。诊断引用证据时**必须落到具体轮次**,"这次浪费多"不是证据,"第 7 轮那句话触发 23 次请求"才是 |
| `metric_confidence` | 每个指标的可信度。**`estimated` 的数字在报告里必须带"约",且不能作为唯一证据支撑一条诊断**;`exact` 才可以直接当事实陈述 |
| `schema_health` | `degraded` 非空 = 本次数据有不可靠的部分,**必须在报告里说明是哪部分**。本产品读的是 Claude Code 未公开承诺的内部日志格式,静默出错的报告比没有报告更糟 |
| `secret_leaks` | 非空则在报告里**单独提醒并给轮换清单**(按 kind 与 source 说明是哪类凭证、第几轮、是你贴的还是助手复述的)。这是安全事项,**不占诊断名额、不进台账**。说明局限:不覆盖工具结果。**绝不复述密钥字符**(脚本已在 `user_messages` 里把命中处替换成 `«已隐去:…»`,不要试图还原) |
| `carry_cost` | 大块内容进上下文后被后续多少次请求反复携带。是"当时那一下"之外的**持续代价**,J3/范围控制类诊断的量化证据。注意它是 estimated,措辞要带"约" |
| `model_fallbacks` | 非空说明实际模型不全是用户选的(内容安全回退等)。评"模型/模式"维度时**必须扣除这部分**,否则冤枉用户 |
| `compact_events` | >0 说明会话触发过上下文压缩,是上下文膨胀的硬证据,计入 token 效率维度 |
| `active_min` | 剔除挂机后的真实投入时长,**"时长与迭代"维度用它**。`duration_min` 是跨度(跨天会话可达几千分钟,主要是挂机),只用于说明会话跨了多久 |
| `effort_distribution` / `skills_used` | 实际推理档位与 skill 归因。评"模型/模式选择"时按**实际 effort** 判,不要只看模型名 |

### 问卷路径(Cursor / Claude.ai / 自动失败)

最多 6 问,能推断的不问:工具和模型、时长与轮次、任务一句话、token 数据(无则 null)、**首条 prompt 原文(必需)**、最大卡点。证据不足的诊断项不输出。

## 第二步:读取档案

档案在 `~/.claude/vibecoding-retro/`,一律通过 `scripts/ledger.py` 读写(不要手工编辑 JSON):

```bash
python3 scripts/ledger.py status          # 缺口台账全貌;自动执行升级/毕业状态转移,transitions 字段即本次台账动态
python3 scripts/ledger.py tips --pending  # 上次的待实践清单
python3 scripts/ledger.py terms --clusters                # 词汇聚类(同领域 ≥3 词才输出)
python3 scripts/ledger.py baseline --complexity M         # 个人基线,任务定档后调;ready:false 则用启发式基准
```

`learnings.md`(建议反馈记录)仍直接读写。

### 冷启动:第一次复盘先回溯

`sessions.jsonl` 不存在或 <3 条时,报告里"上次实践验证""成长轨迹"两段会是空的,基线也 `ready: false`——**而第一次恰恰是用户判断这东西值不值得用的时刻**。所以先提议回溯:

```bash
python3 scripts/parse_session.py --list --days 30 --limit 10
```

> "你机器上有最近 30 天的 N 个会话日志。要不要我一起扫一遍?跨会话才看得见重复踩坑和成长趋势,单看这一次会薄很多。大约多花两三分钟。"

用户同意 → 走下面的《批量复盘》路径,一次把台账建起来;拒绝 → 正常单次复盘,把空的两段直接省略(不要留空标题),并说明"档案积累到 3 次后会出现成长轨迹"。

## 第三步:验证上次实践(先于新诊断)

对上次的每条 tips_to_try,用本次会话数据执行该 KB 条目的"验证"字段:

- 信号显示已实践且指标改善 → `tried-worked`,报告中确认("上次的 KB-24 生效了:重复读取从 4 次降到 0")
- 已实践但没改善 → `tried-failed`,追问一句实际情况,可能是技巧不适配
- 无实践迹象 → 保持 `pending`,报告中轻提醒一次;连续 2 次 pending 则问用户是要 `skipped`(不适合我)还是继续保留——**不做第三次提醒**,尊重用户的取舍

结论用 `python3 scripts/ledger.py tips --set KB-24 tried-worked` 写回(状态:pending/tried-worked/tried-failed/skipped)。

**能给数就给数。** 判"生效了没有"不要只凭印象,跑一次采纳前后的实测对比:

```bash
python3 scripts/ledger.py effect --tip KB-24 --complexity M
```

两侧都是实测中位数,**可以直接陈述**("采纳后同档位会话的活跃时长中位数从 60 分降到 40 分")。但 `reliable:false` 时只能说前后有变化,**不能说是这条建议带来的**——样本不够时相关不是因果。

## 第四步:五维评分(快速)

读 `references/scoring-rubric.md`:token 效率、模型/模式选择、时长与迭代、提示词质量、委托校准,各 1–5 分。缺数据记 N/A。

任务定档后,跑一次和个人基线的偏差——**"超出应有值"的分母只能是用户自己同档位的历史中位数**,不存在通用的"应有值"(L 级任务花 S 级十倍 token 是正常的):

```bash
python3 scripts/ledger.py compare --session-json <解析结果.json> --complexity M
```

- `ready:false`(同档记录 <10)→ **不要在报告里提"超标"**,没有分母就没有超标
- `flagged` 里的指标 → **回到 `prompts[]` 找出是哪一轮造成的、行为原因是什么**。偏差只负责开启调查,不负责下结论;找不到行为原因就不要写进诊断
- 只说 token 和倍数(如"用了你中位数的 2.3 倍"),**不要换算成美元**——订阅制下那是估算的估算,且要维护会过期的定价表

## 第五步:缺口诊断

**完整读 `references/capability-diagnosis.md`**,按 T1–T6、J1–J4 检查。铁律不变:具体证据、假设式措辞、每次最多 2 条、弱证据只入台账。台账升级(确认 3 次 → 结构性)与毕业(连续 5 次未现)机制不变。**同侪口吻**:基本功缺失照说,但说的是"这个习惯在拖累你的产出",不是"你缺乏 XX 能力"。

**J4 必须真的做 diff,不能靠印象**(它是唯一只能跨会话检测的项,漏了就等于没有):

```bash
python3 scripts/trend_report.py --last 10    # series[].waste_flags 是历史的坑,waste_flag_counts 是频次
```

把本次的坑(`repeated_file_reads`/`oversized_tool_results`/`compact_events`/`secret_leaks`/纠偏主题)与历史列表逐项比对,**重合即 J4 候选**,并在证据里写明"这是第 N 次出现"。历史里已被建议沉淀过、这次仍出现的,证据更强。无重合就明确不报 J4。

## 第六步:知识库匹配

读 `references/knowledge-base.md`,用索引表把本次的诊断项和扣分项映射到 KB 条目:

- 每条建议 = 本次证据 + KB 技巧本体 + 来源等级与链接。**命中知识库的建议必须引用条目 ID 和出处**
- 索引未命中且问题重要 → 临场 web 搜索官方文档补一条,并问用户"这条要不要收进知识库?"(收录需符合质量门)
- 采纳的建议写入 tips_to_try(状态 pending),**每次新增待实践最多 2 条**——待实践堆积 = 没有实践

**建议必须个性化,直接搬 KB 原文等于没给建议。** 用户对这类通用最佳实践大多已经知道,增量价值只在"落到我的工作流上"。每条建议过三关:

1. **绑定用户的具体资产**:指名他已有的文件、习惯、项目(如"在你已有的 HANDOFF.md 里加一段"),而不是"建议建立文档习惯"
2. **写成最小改动**:一个可以今天做完的动作,不是一套方法论
3. **自带验证方式**:下次复盘拿什么数据判断它生效了

记录时把这个动作写进 note,**验证时按 note 核对而不是按 KB 条目**:

```bash
python3 scripts/ledger.py tips --add KB-19 --note "<具体动作>。验证:<下次看什么指标>"
```

### 给建议配一个数:反事实圈定

抽象的"注意上下文卫生"没有痛感,**"这一段 48K 白烧了"有**。做法是从 `prompts[]` 里把**已经发生、且已被作废**的消耗圈出来:

1. 在 `user_messages` 里找到转向点——用户改口、推翻前提、发现走错方向的那一轮(记作第 b 轮),以及这条错误路径的起点(第 a 轮)
2. 作废量 = `prompts[b-1].cum_billed_input − prompts[a-1].cum_billed_input`(一次减法,别自己逐轮相加)
3. 写成:"第 a 轮到第 b 轮之间的 XXK 计费 input,在你第 b 轮改口后全部作废"

**这不是模拟,是把实测数字做减法**,所以可以直接陈述,和"预计能省 $0.4"有本质区别——后者是编的,禁止出现。

找不到明确的转向点就不写。**宁可不给数,不要给假的数。**

用户若反馈建议太宽泛,记进 `learnings.md`,后续复盘按上面三关重出。

## 第七步:输出报告

按 `templates/report-template.md`,结构:① 上次实践的验证结果 ② 本次发现与优化建议(正文,含 KB 引用)③ 成长轨迹(台账动态)④ 效率评分卡(紧凑附表)。

报告后问:"这些建议哪些列入待实践?诊断你认吗?"据回答更新档案:

```bash
python3 scripts/ledger.py confirm --gap T4        # 用户确认的诊断(否决用 reject;台账计数只认 confirm/reject)
python3 scripts/ledger.py tips --add KB-24 --note "<具体动作>。验证:<看什么>"
python3 scripts/ledger.py terms --add webhook --domain api-communication   # J1 缺词入台账
# 最后:报告全文 + 记录一起入档
python3 scripts/ledger.py record --session-json <记录.json> --report <报告.md>
```

**报告全文必须归档,这是周报的唯一素材来源。** 把你刚输出的报告原样写进一个 markdown 文件,连同记录一起 `record`——它会复制进 `reports/` 并把路径写进记录。**漏了 `--report`,这一段在周报里就只剩几个数字。**

会话记录按 `templates/session-record.json` 的 schema 写:`session_id`、`project`、`segment`(本段的起止时间戳与轮次区间)三个字段决定下次能不能正确算增量,不要省。record 放最后执行,它同时推进各缺口的"连续未出现"毕业计数。北极星指标随时可查:`ledger.py practice-rate`。`learnings.md` 仍手工追加一行。

## 周报:交叉汇总(用户说"周复盘""周报",或定时任务提醒时)

**周报不是把单次报告拼起来,而是回答单次复盘答不了的问题**:精力实际花在哪、同一个坑在几个项目里重现、习惯有没有在变好。

```bash
python3 scripts/ledger.py weekly-pack --days 7   # 一次拿到全部素材
```

数据包里:`sessions`(本周每段)、`by_project`(项目对比)、`recurring_waste`(≥2 段出现的坑 = J4 硬证据)、`gaps`/`graduated`、`practice_rate`、`tips_to_try`、`reports_to_read`、`coverage`。

`coverage` 是复盘覆盖率(素材来自 SessionEnd 钩子登记的会话索引):

- `available:false` → 钩子没装或本周无记录。**不要因此假装覆盖率是 100%**,如实说"这周有多少段没复盘无从得知"
- `not_retroed` 非空 → 在周报里说明"本周 N 段会话,只复盘了 M 段"。**只陈述,不催促**——用户有权只复盘他在意的那几段,反复催会把这个功能变成负担

**然后必须逐个读 `reports_to_read` 里的报告全文**——数字只能告诉你"发生了什么",报告里才有当时的证据和你给过的建议。跳过这步写出来的周报和单次报告没有区别,那是这个功能唯一的失败方式。

按 `templates/weekly-report.md` 输出,写完归档:

```bash
python3 scripts/ledger.py record --session-json <周报记录.json> --report <weekly.md>
```

周报记录的 `env` 记 `weekly`、`complexity` 留 null,以免污染单次会话的基线统计。

**周报的三条铁律:**

- **诊断仍是最多 2 条**,且优先选跨会话模式;同一缺口跨多段只算一条,`confirm` 只调一次
- **下周只给一件事**——周报给清单会和单次复盘的建议叠加,直接压垮注意力预算
- `reports_missing` > 0、`coverage.not_retroed` 非空,都要在报告里说明,不要假装素材完整

### 批量补录(冷启动或积压)

用户说"复盘今天所有 session"、或冷启动回溯时:`parse_session.py --list --days N` 拿候选 → 逐个解析并出报告归档 → 再跑一次 `weekly-pack` 做汇总。诊断合并去重规则同上。

## 边界与注意

- 只做统计与模式分析,**绝不**把代码内容、密钥、敏感路径写进报告或档案。`user_messages` 里的 `«已隐去:…»` 是脚本做的脱敏,**原样保留,不要还原也不要猜内容**
- **数字的可信度分三级**(见 `metric_confidence`):`exact` 可当事实陈述;`derived` 要说明口径;`estimated` 必须带"约"且不能独自支撑一条诊断。**任何情况下不把 token 换算成美元**
- `schema_health.degraded` 非空时,报告要明说哪部分数据不可靠——本产品读的是未公开承诺的内部日志格式,**说错数字比不说更伤**
- 诊断对象是行为模式,不是人格;禁止心理分析式措辞
- 档案只存指标、缺口计数、KB 条目 ID 与一句话摘要,不存对话原文
- 知识库写入(收录/更新/弃用)一律先给 diff 摘要、经用户确认
- "复盘今天所有 session":逐个采集,诊断合并去重成日报
- 报告语言跟随用户
