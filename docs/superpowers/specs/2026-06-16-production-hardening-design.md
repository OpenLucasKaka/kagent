# Production Hardening Design

## Goal

Make the bounded LangGraph self-correcting agent feel like a small production
library and CLI instead of a demo: observable runs, clear failure semantics,
discoverable tools, maintainable modules, and repeatable verification.

## Current State

The project already has a deterministic LangGraph loop, direct tool tests,
CLI smoke coverage, evaluator cases, metrics summaries, and continuous
iteration scripts. The main production gaps are:

- Run traces do not include stable run metadata such as `run_id`, timestamps,
  or duration.
- CLI failures are represented in JSON but always exit successfully unless
  argparse fails.
- Tool discovery only returns names, not descriptions, commands, or examples.
- Evaluator output is useful but not yet easy to slice during production
  triage.
- `agent.py` and `evaluator.py` are readable but growing toward mixed
  responsibilities.

## Chosen Approach

Use incremental hardening, not a rewrite. Keep the deterministic core and test
style, then add production affordances in small TDD slices:

1. Add run metadata to agent traces and summaries.
2. Add structured tool metadata for CLI and docs.
3. Add opt-in CLI non-zero exit behavior for failed agent runs.
4. Add evaluator filtering by category and case name.
5. Refactor shared logic only after behavior is covered.

This keeps the project stable while making the public surfaces more useful for
automation and operations.

## Alternatives Considered

- Full typed model rewrite with Pydantic: better schemas, but too much churn
  before public output fields are stable.
- Replace deterministic tools with real LLM/tool adapters: more realistic, but
  would weaken reproducibility before the control plane is production-ready.
- Large module split first: improves appearance, but risks moving behavior
  without increasing product value.

## Engineering Standards

- Every behavior change starts with a failing test.
- `scripts/run_checks.sh` remains the production gate.
- CLI output remains JSON for automation.
- New public fields are additive and documented in README.
- Continuous metrics must remain readable after partial failures.

## Acceptance Criteria

- Full check suite passes after every slice.
- Agent traces include run metadata without breaking existing consumers.
- CLI can be used in shell automation with an option that exits non-zero when
  the agent status is `failed`.
- `--list-tools` can expose structured metadata, not just tool names.
- Evaluator can run the full suite and targeted subsets.
- README and iteration log describe new production surfaces.
