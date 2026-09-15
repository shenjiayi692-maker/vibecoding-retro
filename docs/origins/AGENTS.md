# My Coach repository instructions

Before architecture or business changes, read `docs/spec/PRODUCT.md`, `SCOPE.md`, `ARCHITECTURE.md`, `DATA_MODEL.md`, `DETECTOR_SPEC.md`, `SMELLS.md`, `EVALUATION.md`, `PRIVACY.md`, and `IMPLEMENTATION_PLAN.md`. Read the relevant ADRs in `docs/decisions/`.

- Keep Claude-specific parsing and fields inside source adapters. Domain logic consumes canonical events only.
- Raw evidence is immutable and separate from derived features, findings, and recommendations.
- The default product path is local-only and must work without an API key or network access.
- Prefer deterministic evidence. Semantic judgment is optional, minimized, schema-validated, and replaceable.
- Follow fixture-first development. A detector is incomplete without positive, negative, ambiguous, and clean-workflow coverage.
- Preserve evidence links and the Observed / Derived / Inferred / Estimated distinction.
- Treat schema changes as explicit versioned contract changes with migration and regression tests.
- Do not expand the frozen MVP: macOS, Claude Code CLI, completed sessions, post-session review.
- Do not add UI, cloud sync, authentication, billing, other providers, or real-time intervention unless the specifications are changed first.
- For every completed implementation task, run tests, lint, and typecheck and report the results.

If code and specifications disagree, stop and resolve the specification conflict before broad implementation.
