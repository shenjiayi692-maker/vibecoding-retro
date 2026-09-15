<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Vibecoding Retro turns a Claude Code session log into an evidence-backed plain-language retrospective">
</p>

<p align="center"><a href="./README.md">English</a> · <strong>中文</strong></p>

跟 AI 结对写了三小时，不知道时间花在哪了。说一句"复盘"，拿到一个有会话日志支撑的答案，而不是凭感觉。

```bash
git clone https://github.com/shenjiayi692-maker/vibecoding-retro && python3 vibecoding-retro/skills/vibecoding-retro/scripts/parse_session.py --list --limit 3
```

这会读你自己的 Claude Code 日志，打印出它能测到的东西——不用安装、无依赖、数据不离开你的机器。要正经用起来则按下面装成插件。

**Vibecoding Retro** 是一个本地运行的 Claude Code 插件，用来复盘一段 AI 辅助编程到底进行得怎么样。说一句"复盘"或者跑 `/retro`，它会解析会话日志，找出具体的浪费来源，用大白话说明代价，并在每条发现的末尾给出一个下次可以试的改法。

没有网站、服务器、数据库、遥测，也不发任何网络请求。数据留在本地文本文件里，你可以随时查看、修改、纳入版本管理或删除。

## 一份复盘长什么样

```text
观察
核心需求第 17 轮才第一次出现。

代价
在此之前的九次修改，针对的是一个当时还不存在的机制。

下次
动手之前，先用一句话写清楚"做完"应该是什么样。
```

报告刻意避开内部分类法、评级和人格评判。它只谈可观察的行为：重复读同一个文件、工具输出过大、上下文携带、约束提得太晚、一个会话里混入无关工作、缓存复用、以及压缩事件。

## 安装

在 Claude Code 里：

```text
/plugin marketplace add shenjiayi692-maker/vibecoding-retro
/plugin install vibecoding-retro@vibecoding-retro
```

依赖：Claude Code 和 Python 3.9+。插件只用 Python 标准库。

验证日志能否被发现：

```bash
python3 ~/.claude/skills/vibecoding-retro/scripts/parse_session.py --list --limit 3
```

## 怎么用

| 你说 | 插件做什么 |
| --- | --- |
| `复盘` 或 `/retro` | 解析一段会话，产出带证据的发现，并归档报告 |
| `周复盘` 或 `/weekly-retro` | 跨项目比较本周的报告，选出下周的一个重点 |

SessionEnd 钩子只往本地索引追加一条会话 ID、项目和时间戳。它不生成报告、不调模型、不给你发通知。复盘保持为一个主动动作，因为 Claude Code 的会话可以被恢复，也可能跨好几天。

## 证据与度量

流式解析器读取 `~/.claude/projects/*/*.jsonl`，报告：

- token 用量、模型分布、人类轮数、活跃时长、推理强度、缓存复用；
- 每个人类 prompt 对应的请求数、工具调用、token 和上下文增长；
- 重复读取、超大输出、上下文携带、压缩事件；
- 当 Claude Code 未公开的日志格式发生变化时，给出 schema 健康告警；
- 指标置信度分为 `exact`、`derived`、`estimated` 三档。

估算值必须被描述为近似，且不能单独支撑一条发现。工具从不把 token 折算成金额。

个人基线要在至少十次可比会话之后才出现。偏离基线只是开启一次调查，本身不是结论——报告仍然必须把差异追溯到具体某一轮和某个行为。

## 本地数据与密钥处理

所有内容存放在 `~/.claude/vibecoding-retro/` 下：

| 路径 | 内容 |
| --- | --- |
| `sessions.jsonl` | 已复盘会话的指标，只追加 |
| `reports/` | 完整的单次与每周复盘报告 |
| `notes.json` | 建议与检查项，只追加 |
| `session-index.jsonl` | 钩子写入的会话 ID、项目、时间戳 |

扫描覆盖人类消息，以及助手的推理和回复。发现会标出位置、来源、密钥类型和长度，并把密钥本身替换成脱敏标记。工具执行的输出**不在**密钥扫描范围内。

## 开发与验证

```bash
python3 -m unittest discover tests
```

81 个测试覆盖精确记账、prompt 归因、上下文携带、置信度标签、schema 漂移、密钥脱敏、误报、报告归档、增量边界、周聚合，以及钩子静默失败。测试夹具里的密钥是合成占位符。

## 边界

- 自动采集只支持 Claude Code，因为它依赖本地会话日志。
- Cursor 和 Claude.ai 走一份简短的证据问卷，而不是自动解析。
- 解析器依赖一个内部的、未公开的日志格式；健康检查能暴露退化，但上游的大改动仍可能需要维护。
- 这个工具评估的是工作流，不是人，也不提供产品策略或职业规划建议。
