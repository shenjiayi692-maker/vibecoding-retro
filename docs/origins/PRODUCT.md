# Product Specification

Status: **Frozen for pre-code MVP**  
Specification version: `0.2.0`  
Last reviewed: 2026-08-12  
Evidence cut-off: 2026-08-12

## Product definition

**My Coach** is a local-first, evidence-backed post-session workflow profiler and coach for completed Claude Code sessions on macOS.

It answers:

- What task did this session attempt?
- What happened across context gathering, action, correction, and verification?
- Which task-conditioned workflow smells are supported by observable evidence?
- What consequence was observed, derived, inferred, or estimated?
- What specific experiment should the user try next time?
- Did the recommendation improve comparable later sessions without harming outcomes?

The product is not a prompt grader and is not primarily a token dashboard.

## Target user

MVP user: an individual developer or technical builder using Claude Code CLI on macOS for non-trivial coding work who wants to improve personal AI workflow.

The user is not expected to be a workflow expert. They may annotate observable facts and dispute evidence; they are not the source of expert truth.

## MVP experience

Input:

```text
completed local Claude Code CLI session
```

Output:

```text
task reconstruction
→ outcome evidence
→ workflow timeline
→ up to three default-visible findings
→ evidence and counterevidence
→ task-specific recommendation
→ optional feedback for later calibration
```

Default analysis is **Local Only**. It needs no API key, makes no semantic-provider call, and produces a complete baseline review plus deterministic findings. **AI-Assisted** mode is opt-in and may use an Anthropic API key for bounded semantic decisions.

## Workflow-quality model

The product reports dimensions separately and never collapses them into an unexplained score.

| Dimension | Question | Preferred evidence |
|---|---|---|
| Outcome | Was the requested result achieved? | task-appropriate checks, retained changes, explicit acceptance |
| Framing | Were goal, critical context, constraints, and success conditions available when needed? | turn chronology, referenced files, later correction/rework |
| Direction | Did the trajectory converge? | strategy changes, milestones, corrections, abandoned work |
| Verification | Was completion grounded in environment evidence? | tests, build, lint, diff, screenshot, user acceptance |
| Context relevance | Did the active context remain relevant and proportionate? | task boundaries, context snapshots, repeated/stale content |
| Recovery | Did the workflow learn after failure? | changed hypothesis or action following errors/corrections |
| Safety/scope | Were explicit boundaries respected? | touched resources, permissions, non-goals, side effects |

Token and dollar usage support these dimensions but are not the objective function.

## Product principles

1. **Outcome before efficiency.** Optimize safety, correctness, task completion, and reliable verification before time, tokens, or cost.
2. **Evidence before advice.** Every finding includes supporting evidence, material counterevidence, missing evidence, confidence, and applicability.
3. **Diagnose a trajectory, not a person.** Do not label a user as good or bad at prompting.
4. **Task-conditioned guidance.** No Plan Mode is not automatically Premature Implementation; many reads are not automatically Context Pollution.
5. **Precision before coverage.** Abstain when evidence is weak. A silent coach is better than an irrelevant lecturer.
6. **Deterministic-first.** Structural and numeric facts are calculated locally. Optional semantic judgment cannot bypass evidence gates.
7. **Local-first.** Raw prompts, code, tool output, and transcripts remain on-device by default.
8. **Explicit uncertainty.** Claims are labeled Observed, Derived, Inferred, Estimated, or Unavailable.
9. **Version everything.** Parser, schema, feature, detector, judge prompt, rubric, and recommendation versions are recorded.
10. **Advice is falsifiable.** Each recommendation names an intended outcome and guardrail for later comparison.

## Competitive baseline

Claude Code already provides `/usage`, `/context`, and `/insights`; mature tools such as `ccusage` already aggregate local token and cost data. My Coach must therefore differentiate through per-session, versioned findings with evidence references, counterexamples, abstention, calibration, and recommendation follow-up. A generic session summary or prettier usage chart is insufficient.

## MVP success criteria

- Imports supported Claude Code CLI sessions read-only on macOS.
- Produces Review JSON Contract `0.1` with no network and no API key.
- Keeps Claude fields inside the adapter boundary.
- Implements exactly the five frozen smells in `SMELLS.md`.
- Each detector has positive, negative, ambiguous, and clean-workflow fixtures.
- Every displayed finding can open or identify its local evidence.
- High-confidence findings meet the precision release gate in `EVALUATION.md`.
- No recommendation is emitted without a finding and applicable evidence.
- Token accounting reuses or integrates mature logic where licensing/API fit permits.
- The review is more specific and auditable than the same user's Claude Code `/insights` result.

## Non-goals

- universal prompt or workflow score;
- real-time intervention or prompt rewriting;
- Windows/Linux or other coding-agent providers;
- cloud sync, accounts, authentication, billing, or team surveillance;
- automated changes to CLAUDE.md, skills, hooks, permissions, or source code;
- hidden-reasoning reconstruction;
- proof that generated code is correct;
- token minimization as the primary goal.

## Current official basis

- [Claude Code best practices](https://code.claude.com/docs/en/best-practices) — continuously updated, no publication date shown; checked 2026-08-12.
- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works) — continuously updated, no publication date shown; checked 2026-08-12.
- [Commands reference](https://code.claude.com/docs/en/commands) — continuously updated, no publication date shown; checked 2026-08-12.
- [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — published 2026-01-09; checked 2026-08-12.

Official guidance is evidence, not timeless law. Product and detector versions must change when models, Claude Code behavior, or empirical results change.
