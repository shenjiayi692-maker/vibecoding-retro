# HANDOFF:vibecoding-retro v2.5 代码层实现

交接对象:Claude Code / Cowork 会话。本文件是唯一入口,读完后按任务清单执行。
配套文件:`skills/vibecoding-retro/`(skill 源码,已完成)、`vibecoding-retro-PRD.md`(产品定义,冲突时以 PRD 为准)。

## 一、你要做什么(一句话)

为已完成的 vibecoding-retro skill 补一层**确定性 Python 脚本**,把目前靠 LLM 临场发挥的解析、统计、台账读写变成可测试的代码;LLM 只保留判断类工作。

## 二、核心架构决定(不要偏离)

**确定性层(写成脚本)与判断层(留给 LLM)的分界:**

| 工作 | 归属 | 理由 |
|---|---|---|
| 会话文件发现、JSONL 解析、token/轮次/时长聚合 | 脚本 | 机械、量大、必须精确 |
| 浪费模式检测(重复读文件、超大工具结果、缓存命中率、上下文膨胀) | 脚本 | 纯计数,token-dashboard 已验证可行 |
| 用户消息全文抽取(供 LLM 阅读) | 脚本 | 抽取是机械的 |
| 纠偏识别、任务复杂度定档(S/M/L) | LLM | 语义判断 |
| 能力诊断(T1–T6、J1–J4 信号识别) | LLM | 本产品核心价值,依赖对话语义理解,**禁止用关键词匹配脚本替代** |
| 台账读写、升级/毕业状态机、基线计算 | 脚本 | 状态转移必须确定、可测试 |
| 报告撰写 | LLM | 按模板 |

**约束:**
- Python 3.9+,**仅标准库**(json/pathlib/statistics/argparse/datetime),零 pip 依赖——参照 claude-usage 和 token-dashboard 的做法,保证任何装了 Claude Code 的机器直接能跑
- 无网络请求;绝不把代码内容/密钥/敏感路径写入任何输出
- 每个脚本可独立 CLI 运行,输出 JSON 到 stdout,便于 skill 内调用和单测

## 三、任务清单(按序执行)

### 任务 1:`scripts/parse_session.py`

输入:`--file <jsonl路径>` 或 `--latest`(自动找 `~/.claude/projects/*/​*.jsonl` 最近修改的,列出前 5 供确认)。

输出 JSON(stdout),契约如下:

```json
{
  "session_id": "...", "project": "路径", 
  "start": "ISO时间", "end": "ISO时间", "duration_min": 45.2,
  "models": {"claude-sonnet-4-6": {"messages": 30}},
  "tokens": {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
  "user_turns": 22,
  "user_messages": [{"turn": 1, "text": "...", "ts": "..."}],
  "tool_stats": {
    "calls_by_tool": {"Read": 15, "Edit": 8},
    "repeated_file_reads": [{"path": "src/a.py", "count": 4}],
    "oversized_tool_results": [{"turn": 12, "est_tokens": 45000}],
    "cache_hit_rate": 0.83
  },
  "input_token_trend": [{"turn": 5, "input_total": 80000}],
  "warnings": ["schema字段缺失时在此说明,不要崩"]
}
```

实现要点:流式逐行解析(文件可达几十 MB,禁止整读);字段缺失容错(Claude Code 日志 schema 可能变化,解析不到的字段置 null 并进 warnings);`user_messages` 要过滤掉工具结果类 user 消息(JSONL 里 tool_result 也挂在 user role 下——只留真人输入);oversized 判定用 `len(text)//4` 粗估 token。

### 任务 2:`scripts/ledger.py`

台账状态机,子命令:

- `record --session-json <文件>` — 追加一条到 `~/.claude/vibecoding-retro/sessions.jsonl`(schema 见 skill 的 templates/session-record.json)
- `confirm --gap T4` / `reject --gap T4` — 更新 gap-ledger.json 计数
- `tips --add KB-24` / `tips --set KB-24 tried-worked` / `tips --pending` — 待实践清单管理(状态:pending / tried-worked / tried-failed / skipped)
- `practice-rate` — 输出建议实践率 = (tried-worked + tried-failed) / 全部非 skipped 条目,这是产品北极星指标
- `status` — 输出全部缺口状态,并执行状态转移:confirmed≥3 → structural;rejected≥2 → suppressed(停检);structural 且连续 5 次 session 未出现 → graduated
- `terms --add webhook --domain api-communication` / `terms --clusters` — 词汇台账与聚类(同 domain ≥3 词即输出聚类)
- `baseline --complexity M` — 从 sessions.jsonl 取同档记录,≥10 条时输出各指标中位数,不足则输出 `{"ready": false, "count": n}`

状态转移规则以 skill 的 `references/capability-diagnosis.md` 为准,实现前先读它。所有写操作前做 JSON 合法性校验,写坏档案是本项目最严重的 bug。

### 任务 3:改造 SKILL.md 采集与档案段

把 SKILL.md 第一、二、五步中"手工解析"的指引替换为脚本调用(保留问卷路径和 ccusage 路径作为降级);诊断步骤(第四步)**保持原样不动**。改完后 SKILL.md 应明显变短。

### 任务 4:测试

`tests/fixtures/` 下手工构造 4 个小型 JSONL 夹具(每个 30–60 行):

1. `clean_session.jsonl` — 干净会话,断言:无浪费标记、统计数字精确匹配
2. `wasteful_session.jsonl` — 埋入同文件读 4 次 + 一个 40k 工具结果,断言两者都被检出
3. `schema_drift.jsonl` — 删掉部分 usage 字段,断言:不崩、warnings 有内容
4. `ledger_lifecycle` — 不是 JSONL,是一段脚本化调用序列,断言状态机走完 watching → structural → graduated 全程,以及 rejected×2 → suppressed

用 unittest(标准库),`python -m unittest discover tests` 一条命令全绿即为通过。

### 任务 5(可选,时间富余再做):`scripts/trend_report.py`

读 sessions.jsonl 输出近 N 次的指标趋势 JSON,供"周报"场景。不做可视化——报告仍由 LLM 写。

## 四、验收标准

- [ ] 4 个夹具测试全绿
- [ ] 对一个真实 Claude Code 会话日志跑 parse_session.py,数字与 `npx ccusage session` 输出偏差 <5%
- [ ] 完整走一遍复盘流程(用 wasteful_session 夹具):脚本产出 → LLM 诊断 → confirm → 台账更新,全程无手工干预
- [ ] `grep -r "requests\|pip install"` 无结果(零依赖验证)
- [ ] SKILL.md 更新后重新打包(zip 即可),结构完整

## 五、明确不要做的事

- 不要给诊断写关键词匹配脚本(会毁掉产品核心价值,LLM 语义判断不可替代)
- 不要加 SQLite/数据库(JSONL + JSON 文件足够,保持可 git、可手改)
- 不要做 Web dashboard(已有 token-dashboard,不重复造轮子;本产品的界面就是对话)
- 不要动 capability-diagnosis.md、scoring-rubric.md 和 knowledge-base.md 的内容(前两者是产品定义,知识库由用户经"更新知识库"流程维护,写入必须经用户审核 diff)
- 不要给知识库匹配写脚本(诊断项→KB 条目的映射靠 LLM 读索引表,索引会随知识库更新而变)

## 形态

**Claude Code plugin**(内含一个 skill + 两个 slash command + 一个 SessionEnd 钩子)。**界面就是对话**——没有网站、没有服务器、没有数据库,数据是用户本地的几个纯文本文件。定位是**给别人也能装的产品**,不是只给作者自己用的脚本。

## 进度(最后更新 2026-08-03)

- **已完成(v2.6 成本归因与分发形态)**:
  - `prompts[]` 逐轮账单(按 `promptId` 切分,含请求数/工具/token/上下文增长/effort/skill 归因),诊断证据从"这次浪费多"变成"第几轮那句话造成的"
  - `metric_confidence` 指标可信度三级(exact/derived/estimated),SKILL.md 硬约束 estimated 必须带"约"且不能独自支撑诊断;**明令禁止换算美元**
  - `schema_health` schema 自检(版本白名单 + 关键字段存在性),`degraded` 非空必须写进报告——**这是"读未公开日志格式"这个架构赌注的保险单**
  - `carry_cost` 上下文拖拽;`ledger.py compare`(本次 vs 个人基线,分母只能是自己)与 `effect`(建议采纳前后实测对比)
  - 密钥扫描扩到助手 thinking/正文(thinking 明文落盘),**并给解析输出做脱敏**——修了一个真实缺陷:`user_messages` 原文此前会把密钥明文回显进解析结果
  - 改造为 plugin:`.claude-plugin/`、`skills/vibecoding-retro/`、`commands/`(`/retro`、`/weekly-retro`)、`hooks/`(SessionEnd 只登记索引);`weekly-pack` 加 `coverage` 复盘覆盖率
  - 知识库月度协议加三类必过信号:日志 schema 变化 / 官方内置能力 / 同类工具动向
  - 修了一个扫描器误报类:`re_` 前缀会命中 snake_case 标识符(`test_refuses_to_…`),现要求尾部含大写或数字
  - 82 个单测全绿
- **下一步**:① 建 GitHub 远端并把 marketplace 地址填进 README(**用户拍板是否公开**)② 装 plugin 后验证 `/retro` 的实际命名空间(可能是 `/vibecoding-retro:retro`)③ 等真实数据校准:诊断确认率、密钥扫描误报率、`recurring_waste` 阈值(现 ≥2 段)、`COMPARE_FLAG_RATIO`(现 1.5)
- **残留状态**:SessionEnd 钩子**随 plugin 安装才生效**,未装时 `coverage.available` 是 false;历史 5 条记录无 `report_path`(在 `--report` 之前录的)。维护者的个人待办(凭证处置等)不记在本仓库

## 上一轮进度(2026-07-30)

- **已完成(v2.5 代码层,任务 1–5 全部交付)**:`parse_session.py`、`ledger.py`、`trend_report.py`;47 个单测全绿(`python -m unittest discover tests`);5 个夹具;SKILL.md 改造完毕;零依赖验证通过;已装到 `~/.claude/skills/vibecoding-retro/` 并打包
- **已完成(dogfood 后的 v2.5.1 修订)**:实测 5 个真实会话后修了 9 个问题——压缩摘要不再冒充真人轮次、模型安全回退单独标注、密钥扫描(11 类前缀 + 高熵串,不回显密钥字符)、活跃时长 `active_min`、J4 强制跑 diff、批量/周报路径、建议个性化三关、冷启动回溯、`capability-diagnosis.md` 把 J4 移出优先级序列(v2.5 修订,已获用户授权)
- **已完成(报告归档与周报闭环)**:`record --report` 把报告全文归档进 `reports/`;`last-covered` 定义"本段"边界避免重复诊断;`weekly-pack` 组装交叉汇总素材;`templates/weekly-report.md`;launchd 每周五 18:05 生成数据包并通知
- **下一步**:等真实使用数据积累后校准——① 诊断确认率(现 3/3,样本太小)② 密钥扫描的误报率 ③ `recurring_waste` 阈值(现 ≥2 段)
- **残留状态**:`claude setup-token` 未配(不影响,周报走对话路径);历史 5 条记录无 `report_path`(在 `--report` 之前录的),那几周的周报只有数字

## 六、背景速览(需要更多上下文时读 PRD)

产品定位(v2.1):服务高频使用 AI 的产品经理,同侪姿态优化其工作流。核心闭环:发现问题 → 知识库(references/knowledge-base.md,官方文档+建造者实践,带出处分级)给出优化做法 → tips_to_try 记录待实践 → 下次复盘验证。缺口诊断 T1–T6/J1–J4 保留,台账机制不变(确认3次→结构性,5次未现→毕业)。北极星指标:建议实践率 ≥50%。知识库月度更新,先 diff 后写入。
