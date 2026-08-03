# 工作流优化知识库(knowledge base)

**用途**:复盘发现问题后,按诊断类别查到经过验证的更好做法,变成带出处的建议。
**索引方式**:按诊断类别(T1–T6、J1–J4)和浪费标记(waste flags)查,不按来源查。
**来源等级**:`official`(官方文档/官方工程博客)> `verified`(被广泛复现的社区实践、知名建造者一手分享)> `blogger`(单一博主观点)。
**last_updated**: 2026-07-15 · 复盘时若距今 >45 天,提醒用户执行"更新知识库"。

## 索引表

| 诊断/扣分项 | 相关条目 |
|---|---|
| T1 问题定义 | KB-01, KB-02 |
| T2 验收标准 | KB-03, KB-04, KB-05 |
| T3 范围控制 | KB-06, KB-07 |
| T4 假设外显化 | KB-01, KB-08, KB-09 |
| T5 抽象层级切换 | KB-10, KB-11 |
| T6 委托校准 | KB-12, KB-13, KB-14 |
| J1 词汇缺口 | KB-15 |
| J2 方案评估 | KB-11, KB-16 |
| J3 验证行为 | KB-04, KB-17, KB-18 |
| J4 知识沉淀 | KB-19, KB-20, KB-21, KB-28, KB-29 |
| 浪费:重复读文件/上下文膨胀 | KB-22, KB-23, KB-24 |
| 浪费:返工消耗 | KB-02, KB-25 |
| 浪费:整段重跑/走错项目 | KB-29 |
| 模式:该 plan 没 plan | KB-25, KB-26 |
| 模式:模型档位 | KB-27 |

---

## 域一:Prompt 结构与前置信息

**KB-01 · 前置目标而非方案** `[T1][T4]` 通用 · official
首条 prompt 先写"我要解决的问题/我的用户遇到什么",再写(或不写)技术方案,让 AI 有机会挑战你的方案预设。Anthropic 提示工程文档的核心原则"clear and direct"强调把任务背景、动机、受众交代清楚——模型知道"为什么"时,方向性错误显著减少。
出处:https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview · 2026-07 收录
验证:后续 session 中"其实我真正想要的是"类推翻不再出现。

**KB-02 · 具体指令减少来回** `[T1][返工]` Claude Code · official
Anthropic 官方最佳实践明确:指令越具体,首次成功率越高,来回纠正越少。差:"给 foo.py 加测试";好:"给 foo.py 写测试,覆盖用户未登录的边界情况,不要用 mock,参照 tests/ 里现有风格"。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:纠偏轮次(correction_turns)相对基线下降。

**KB-03 · 验收标准写进首条** `[T2]` 通用 · official
在首条 prompt 末尾加一段"完成标准:1) … 2) …",格式可用 Given-When-Then 或简单清单。官方最佳实践建议让 Claude 先知道"怎么算通过"(如给出测试用例或预期输出样例),这也是 TDD 工作流的前提。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:"看到输出才发现需求"的大改不再发生。

**KB-04 · 测试先行(TDD with AI)** `[T2][J3]` Claude Code · official
让 Claude 先写测试并确认失败,再写实现直到通过。官方列为 agentic coding 的推荐工作流:验收标准物化成了测试,验证自动发生。适合逻辑类任务,UI 类可改用"先给截图/样例作为 target"。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:bug 后置爆发消失;J3 信号不再出现。

**KB-05 · 给视觉目标** `[T2]` 通用 · official
UI/前端任务把设计稿截图、参考网站或手绘线框直接贴给模型作为验收基准,迭代"对着目标改"而不是"凭感觉改"。官方最佳实践称之为 visual targets,可大幅减少主观来回。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:UI 类任务轮次下降。

## 域二:范围与任务切分

**KB-06 · out-of-scope 清单** `[T3]` 通用 · verified
首条 prompt 加一行"本次不做:X、Y、Z"。负面清单对 LLM 的约束力经常强于正面描述(模型倾向热心加料),对自己同样是 scope 承诺。多位建造者反复分享的实践,与本项目 HANDOFF 的"明确不要做"同理。
出处:follow-builders 建造者社区多次出现的共识实践 https://github.com/zarazhangrui/follow-builders · 2026-07 收录
验证:"顺便再加个"话术频次下降;成品与首条描述的偏差缩小。

**KB-07 · 新想法进停车场** `[T3]` 通用 · verified
会话中冒出的新需求不当场做,回一句"记到 backlog,本次不做",复盘时统一处理。配套技巧:在项目里维持一个 IDEAS.md,让 AI 帮你把会话中的即兴想法自动归档进去。
出处:社区通行实践,多个 agentic coding 工作流分享中出现 · 2026-07 收录
验证:单会话目标数回到 1;scope creep 标记消失。

## 域三:上下文卫生

**KB-22 · 主动 /clear 与 /compact** `[重复读文件][上下文膨胀]` Claude Code · official
任务切换时用 /clear 清空上下文,长任务中途用 /compact 压缩。官方最佳实践指出无关上下文会稀释注意力、推高成本;上下文膨胀还会放大"重复读同一文件"的浪费。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:input token 趋势曲线不再单调爬升;cache 命中率回升。

**KB-23 · 子代理隔离脏活** `[上下文膨胀]` Claude Code · official
大范围探索(读几十个文件找某个逻辑)交给 subagent,主上下文只收结论。Anthropic 的上下文工程文章把"隔离"列为核心策略之一:探索产生的海量中间内容不应污染主线。
出处:https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents · 2026-07 收录
验证:oversized_tool_results 标记减少;主会话 token/轮次下降。

**KB-24 · 结构说明进 CLAUDE.md** `[重复读文件]` Claude Code · official
同一文件被反复读取,说明项目结构信息没有沉淀。把关键文件的职责地图写进 CLAUDE.md("支付逻辑在 src/pay/,入口是 handler.ts"),模型就不必每次重新探索。
出处:https://www.anthropic.com/engineering/claude-code-best-practices ; https://docs.claude.com/en/docs/claude-code/memory · 2026-07 收录
验证:repeated_file_reads 标记消失。

## 域四:模式与模型选择

**KB-25 · 复杂任务先 plan 后写** `[该plan没plan][返工]` Claude Code · official
L 档任务的官方推荐流程:先让 Claude 读代码并出方案(plan mode 或明确说"先不要写代码,给我方案"),人审方案后再执行。方案层面的错误在 plan 阶段纠正是一句话,在代码阶段纠正是一次返工。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:L 档任务的架构级返工消失。

**KB-26 · 用"think"分档要求思考深度** `[该plan没plan]` Claude Code · official
在 prompt 里用 think / think hard / ultrathink 触发不同深度的扩展思考,难题给足思考预算。适合方案设计、疑难 debug;简单任务不要用(白花 token)。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:T5 死磕模式减少——模型在动手前就排除了坏路径。

**KB-27 · 模型档位经济学** `[模型档位]` 通用 · verified
经验法则:探索、问答、机械改动用中低档;方案设计、跨文件重构、疑难 debug 用高档。判断依据是"错误的代价"——错了要大返工的环节值得贵模型,错了改一句的环节不值得。社区共识 + 各官方定价页的隐含逻辑。
出处:综合 Anthropic/OpenAI 模型选择文档与社区实践 · 2026-07 收录
验证:评分卡"模型/模式"维度不再因档位错配扣分。

## 域五:委托边界(AI 时代 PM 的核心)

**KB-12 · 决策权矩阵** `[T6]` 通用 · verified
把决策分两类:判断类(做什么、为谁做、先做哪个、接受什么代价)必须自己拿主意,AI 只提供选项和依据;执行类(样板代码、语法、格式、机械重构)充分放权,只验收不插手。检验句式:向 AI 要"选项+各自代价",而不是"你决定"。
出处:Anthropic building effective agents 中人机分工原则的应用延伸 https://www.anthropic.com/engineering/building-effective-agents · 2026-07 收录
验证:委托校准维度得分回到 4+。

**KB-13 · 要 trade-off 不要答案** `[T6][J2]` 通用 · verified
产品或技术取舍时,固定句式:"给我 2–3 个方案,各自的代价、规模化后的表现、最简版本分别是什么"。这保留了你的决策权,同时把 AI 用在它擅长的穷举与分析上。
出处:建造者社区通行实践(follow-builders 源中 PM 类建造者反复提及的模式)https://github.com/zarazhangrui/follow-builders · 2026-07 收录
验证:J2"零质疑接受首个方案"信号消失。

**KB-14 · 机械活整批外包** `[T6]` 通用 · official
发现自己手动做重复操作(逐个改导入、手查语法、格式校对)立即停下,把规则描述给 AI 批量执行。官方最佳实践:Claude 适合一次性给清晰规则的批量机械任务。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:"我自己手动改了"话术消失。

## 域六:验证与技术判断

**KB-17 · 每步验收 30 秒** `[J3]` 通用 · verified
每个改动后花 30 秒:看 diff 摘要、跑一下、确认再继续。节奏是"小步快验",不是"攒一堆一起看"。bug 越晚发现,定位成本越高——这在 AI 生成代码上尤其成立,因为你没有逐行写过的记忆。
出处:社区共识实践;与官方 TDD 工作流(KB-04)互补 · 2026-07 收录
验证:回溯式排查("之前哪步改错了")不再出现。

**KB-18 · 让 AI 自证** `[J3]` Claude Code · official
要求 Claude 每次改动后自己跑测试/lint 并汇报结果,可通过 CLAUDE.md 规则固化("每次修改后运行 npm test 并报告")。验证成本趋近于零,习惯就建立得起来。
出处:https://www.anthropic.com/engineering/claude-code-best-practices (CLAUDE.md 记录常用命令与规范) · 2026-07 收录
验证:J3 信号消失且不依赖你的自觉。

**KB-16 · 三个万能追问** `[J2]` 通用 · verified
接受任何技术方案前问三句:trade-off 是什么?数据/流量大十倍会怎样?最简方案是什么?不需要你有能力提出替代方案,只需要有能力触发比较。
出处:工程社区通行的方案评审框架,建造者访谈中反复出现 · 2026-07 收录
验证:架构级返工前置为方案阶段的讨论。

**KB-15 · 缺词就地补课** `[J1]` 通用 · verified
发现自己在绕圈描述某个概念,当场问一句"这个东西的标准术语叫什么?顺便用一句话解释它和相邻概念的区别"。30 秒补一个词,长期消除一类模糊 prompt。台账聚类出的领域则值得花一晚系统过官方术语表。
出处:通用学习实践 · 2026-07 收录
验证:missing_terms 增速放缓;同领域不再重复缺词。

## 域七:沉淀与复利

**KB-19 · CLAUDE.md 是活文档** `[J4]` Claude Code · official
每次踩坑后立刻问自己:这个教训能不能写成一条 CLAUDE.md 规则?官方最佳实践强调 CLAUDE.md 应记录常用命令、代码规范、已知陷阱,并持续迭代——它是所有会话的共享前置知识,一次沉淀全部受益。
出处:https://www.anthropic.com/engineering/claude-code-best-practices ; https://docs.claude.com/en/docs/claude-code/memory · 2026-07 收录
验证:J4 跨会话重复踩坑检测不再触发。

**KB-20 · 重复流程变 skill/命令** `[J4]` Claude Code · official
同一套操作流程第三次出现时,把它固化成 custom slash command 或 skill(.claude/commands/ 或 skills 目录)。判断标准:你已经能把流程口述清楚 = 它可以被固化。
出处:https://www.anthropic.com/engineering/claude-code-best-practices · 2026-07 收录
验证:该流程的会话轮次骤降。

**KB-21 · 会话末尾一分钟沉淀** `[J4]` 通用 · verified
每次 session 结束前让 AI 回答:"本次有什么值得写进 CLAUDE.md/笔记的?"由 AI 提炼、你只做取舍。本 skill 的复盘流程已内置此环节——采纳建议时顺手完成沉淀。
出处:社区通行实践 · 2026-07 收录
验证:知识沉淀率(建议实践率的子项)上升。

**KB-08 · 隐含前提自查清单** `[T4]` 通用 · verified
发 prompt 前 10 秒过一遍:目标用户?平台?数据格式与规模?输出语言?已有约定?性能预算?清单可以直接贴在常用位置(或做成 snippet)。所有"哦对了忘了说"都对应清单上的某一项。
出处:由 T4 缺口的常见前提归纳,社区 prompt checklist 实践 · 2026-07 收录
验证:correction_turns 中"补前提"类降为 0–1。

**KB-09 · 让 AI 先复述再动手** `[T4]` 通用 · official
复杂任务发出后先加一句"动手前,用三句话复述你对任务的理解和你打算的做法"。隐含前提的错位在复述里立刻暴露,成本一轮,收益可能是十轮。
出处:Anthropic 提示工程文档中 chain-of-thought / 确认理解类技巧的应用 https://docs.claude.com/en/docs/build-with-claude/prompt-engineering/overview · 2026-07 收录
验证:方向性返工在第 1–2 轮内被拦截。

**KB-10 · 卡三轮就升维** `[T5]` 通用 · verified
同一问题连续 3 轮修不好,强制触发升维句式:"停一下,退回方案层——我们原来的做法还成立吗?有没有别的路?"把"上升一层"从本能变成规则,规则可以写进 CLAUDE.md 让 AI 主动提醒你。
出处:工程 debug 通行启发式;与 KB-26 think 分档配合 · 2026-07 收录
验证:死磕段(同层穷举 >15 轮)不再出现。

**KB-11 · 环境怀疑优先** `[T5][J2]` 通用 · verified
反复失败且改动"理应有效"时,优先怀疑环境与前提(版本、缓存、配置、数据)而不是继续改代码——这是死磕循环最常见的成因。让 AI 列出"如果代码没错,还有什么会导致这个现象"。
出处:工程社区通行 debug 启发式 · 2026-07 收录
验证:同上,死磕段消失。

**KB-29 · HANDOFF 进度段** `[J4][整段重跑]` Claude Code · verified
交接文档普遍只写"要做什么",不写"做到哪了",于是隔夜或断线后续跑只能凭记忆重发指令——结果是整段重跑、甚至在错误的项目目录里开工。做法:在 `HANDOFF.md` 末尾维持一个进度段(已完成 / 下一步 / 残留状态如未跑的迁移、未填的 key),每个任务块结束时更新;恢复时用"读进度段和 git status,复述你判断的当前位置再动手"代替复述任务。机制:把会话状态外置成文件,续跑就不再依赖上下文窗口或人的记忆——与官方上下文工程文章"长任务用外部笔记持久化状态"同理。可写进 CLAUDE.md 让它自动执行。
出处:用户原创实践(2026-07 复盘中从跨 5 个 session 的重跑模式归纳);机制支撑见 https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents · 2026-07 收录
验证:逐字重发同一条 prompt 的次数归零;不再出现走错项目目录的误启动。

**KB-28 · 订阅高信号源** `[J4]` 通用 · verified
用 follow-builders(建造者精选摘要,含 Anthropic Engineering、Claude Blog、Boris Cherny/Karpathy/Alex Albert 等 26 位建造者)替代算法信息流,每周固定摄入一次。本知识库的月度更新即以它和官方 changelog 为固定信号源。
出处:https://github.com/zarazhangrui/follow-builders · 2026-07 收录
验证:知识库更新时你能主动提名新条目。

---

## 月度更新协议(用户说"更新知识库"时执行)

1. **信号源清单**(按序过一遍):Anthropic Engineering(anthropic.com/engineering)与 Claude Code changelog;follow-builders 最近一月摘要(仓库 README 列出的中心 feed);Cursor changelog 与文档;OpenAI/Vercel 官方博客中 agentic 工作流相关;用户临场提名的来源

   **另有三类信号不产出 KB 条目,但每月必须过,过完在报告里给一句结论:**

   | 信号 | 看什么 | 为什么是必须的 |
   |---|---|---|
   | Claude Code 日志 schema | changelog 里有没有动会话日志字段;跑一次 `parse_session.py --latest` 看 `schema_health.degraded` 是否非空 | **本产品的整个数据层押在未公开承诺的内部格式上**。官方改字段不会通知,解析器会静默失真——错数字比没数字更危险。这是这个架构选择的保险单 |
   | 官方内置能力 | `/usage`、`/context`、status line 的新能力 | 避免继续投入官方即将内置的东西 |
   | 同类工具 | ccusage、cost-analysis、claude-code-cost、Token Optimizer 等 | **不是为了抄功能**,是为了确认"诊断个人能力缺口"这块地还空着。它们做的是用量报表和规则化浪费检测,和本产品不在一个层 |

   发现 schema 变更或 `degraded` 非空 → 这是**最高优先级**,先修解析器,再谈知识库。
2. **候选过滤**:可操作 + 有机制解释 + 不与官方冲突(冲突则双记并标注);拒收玄学咒语和不可验证的提效宣称
3. **产出 diff 摘要**:新增(条目全文)/ 修订(改动点)/ 标记 deprecated(原因),**展示给用户审核,确认后才写入**
4. 更新 last_updated;被 deprecate 的条目保留原文并注明原因,不删除
