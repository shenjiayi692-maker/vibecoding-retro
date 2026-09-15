# MVP Scope

Status: **Frozen**  
Version: `0.2.0`  
Last reviewed: 2026-08-12

## Scope statement

The MVP reviews **completed local Claude Code CLI sessions on macOS**. It is a post-session product. The architecture is provider-agnostic, but the implementation has one provider adapter.

## In scope

### Source and platform

- macOS;
- Claude Code CLI local session discovery in user-approved locations;
- explicit transcript/session selection;
- supported JSONL parsing, read-only;
- optional import of an already configured local OpenTelemetry export;
- schema fingerprinting, diagnostics, deduplication, and partial-parse reporting.

### Processing

- provider-specific raw data → canonical events;
- session/turn/request/tool/file/command/subagent/context/usage reconstruction;
- task segmentation with uncertainty;
- deterministic feature extraction;
- provider-reported usage preservation and local price estimates;
- Review JSON Contract `0.1` plus Markdown/terminal rendering.

### Coaching

- the five smells frozen in `SMELLS.md`;
- applicability and missing-evidence gates;
- evidence and counterevidence;
- severity and confidence as separate values;
- zero to three default-visible findings;
- concrete, falsifiable recommendations;
- local feedback on usefulness, applicability, and evidence.

### Analysis modes

**Local Only — default**

- no key required;
- no external model calls;
- deterministic review and deterministic findings remain available;
- semantic-dependent findings abstain or remain lower confidence rather than failing the review.

**AI-Assisted — explicit opt-in**

- Anthropic API is the only MVP semantic provider;
- uses minimized, redacted evidence fragments;
- supports bounded semantic labels defined in `DETECTOR_SPEC.md`;
- absence or failure of the key/provider falls back to Local Only.

### Evaluation

- synthetic fixtures and consented real-redacted fixtures;
- fact-based annotation rubric;
- positive, negative, ambiguous, and clean-workflow coverage;
- detector, judge, recommendation, and end-to-end evaluation;
- comparison with Claude Code `/insights` as a product baseline.

## Explicitly out of scope

- Windows or Linux support;
- Codex, Gemini CLI, Cursor, Copilot, or any second provider adapter;
- live, pre-action, or real-time intervention;
- prompt interception or automatic rewriting;
- UI/dashboard before Tasks 000–015 stabilize the data pipeline;
- desktop wrapper or mobile app;
- cloud backend, sync, authentication, billing, subscription, or team dashboard;
- employee ranking, monitoring, or productivity scores;
- proprietary model training or fine-tuning;
- OpenAIJudge, LocalModelJudge, OllamaJudge, or other semantic providers;
- automatic configuration or execution of recommendations;
- hidden reasoning content;
- exact subscription-quota reconstruction;
- a sixth workflow smell.

These items belong in backlog and require a specification/ADR change before implementation.

## Supported input contract

An input is supported only when:

1. it is a completed Claude Code CLI session located on macOS;
2. its raw format is represented by a versioned fixture or recognized schema fingerprint;
3. discovery is confined to user-approved roots;
4. unsupported records are surfaced rather than silently discarded;
5. analysis preserves the source file unchanged.

Desktop, web, VS Code, and remote histories are not assumed compatible with the CLI store.

## First interface

Names remain provisional, capabilities are frozen:

```text
my-coach sessions list
my-coach review <session-id-or-path> --format json|markdown
my-coach findings <session-id> [--all]
my-coach feedback <finding-id> <useful|not-useful|wrong-applicability|wrong-evidence>
my-coach doctor
```

Static local HTML may follow from the same JSON contract after the pipeline is stable; it cannot contain separate business logic.

## Release gates

- Local Only end-to-end succeeds with outbound network disabled.
- No API key path is fully tested.
- Raw transcript hashes are unchanged after import and review.
- No Claude-specific payload reaches business/detector code.
- Each smell meets its evidence and fixture requirements.
- Experimental or low-confidence results are hidden by default.
- No secrets appear in logs, safe exports, or persisted judge packets.
- Tests, lint, and typecheck pass.
- Official product sources are rechecked within 30 days of release.

## Change rule

Adding a platform, provider, semantic backend, real-time behavior, cloud feature, team feature, UI phase, or smell changes scope. Update affected specifications and add/replace an ADR before code merges.
