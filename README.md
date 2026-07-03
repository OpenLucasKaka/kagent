# Kagent

Production-shaped LangGraph agent runtime for internal, non-coding workflows.

It provides two execution paths:

- deterministic graph runs for local tests, demos, and regression checks;
- a Codex-style runtime that plans with an OpenAI-compatible LLM provider,
  executes policy-gated tools, records structured observations, and can replan
  after failures.

The project is intentionally conservative: bounded iterations, strict JSON
plan parsing, explicit tool schemas, approval gates for risky actions, compact
operator output, and redacted production evidence.

## Quick Start

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/run_checks.sh
```

Run a deterministic goal:

```sh
.venv/bin/python -m kagent.cli "calculate 2 + 3"
```

Start the LLM-backed terminal agent after setting provider environment
variables:

```sh
# Set KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY, and
# KAGENT_LLM_MODEL in your shell or secret manager.

.venv/bin/python -m kagent.cli
```

After package installation, the console entrypoint is the same daily-use
interface:

```sh
kagent
```

TTY sessions show live progress and a compact operator transcript by default.
Use `/json`, `/compact`, `/last`, `/trace`, `/memory`, `/clear`, and `/help`
inside the shell. Persisted session memory is owner-only and redacts common
API keys, bearer tokens, and URL credentials before writing to disk. The CLI
defaults to the runtime interactive shell, with three planning iterations per
turn. TTY sessions persist memory by default at
`${XDG_STATE_HOME:-~/.local/state}/kagent/session-memory.json`; set
`KAGENT_SESSION_MEMORY_PATH` to override that path or to an empty value to
disable default persistence. Use `--max-iterations` to override the iteration
budget, `--session-memory PATH` for an explicit memory file, `--runtime-plan`
for deterministic runtime tests, and `--interactive-json` when you need full
traces. Runtime and service config values must use JSON integers, not strings
or booleans.

## What It Can Do

The runtime currently includes tools for:

- notes and structured artifacts;
- task lists, rubrics, text transforms, and decision matrices;
- approved HTTP GET requests with SSRF protections;
- opening URLs in the local browser;
- approved bounded local shell commands for internal CLI checks;
- creating workspace files through an audited `apply_patch` flow.

Risky tools are policy-gated. Runs expose structured events, observations,
approval state, artifacts, and metrics so internal dashboards can inspect what
happened without reading raw traces by default. Runtime summaries include
compact fields such as `progress_event_count` for timeline-oriented UIs.

## Service

Start the local HTTP service:

```sh
kagent-serve --host 127.0.0.1 --port 8000
```

Useful endpoints include:

- `GET /health`, `HEAD /health`, `GET /ready`, `HEAD /ready`
- `GET /config`, `GET /version`, `GET /tools`, `GET /runtime/tools`
- `POST /run`, `POST /runtime/run`, `POST /runtime/resume`
- `GET /runtime/runs`, `GET /runtime/runs/summary`
- `GET /runtime/approvals`, `GET /runtime/approvals/summary`
- `GET /metrics`, `GET /metrics.prom`, `GET /openapi.json`

Use `deploy/env.example` for environment variable names and
`docs/deployment.md` for deployment defaults, auth, trace persistence, runtime
tool policy, diagnostics protection, and production preflight checks.

## Code Organization

- `src/kagent/core/`: deterministic LangGraph loop.
- `src/kagent/runtime/`: LLM runtime, policies, tools,
  and typed runtime data.
- `src/kagent/service/`: stdlib HTTP service, routing,
  status, approvals, resume/cancel, trace store, and transport helpers.
- `src/kagent/cli/`: command line and interactive
  terminal UI.
- `src/kagent/providers/`: OpenAI-compatible provider
  and fake provider test support.
- `src/kagent/eval/`: evaluation cases and runner.
- `src/kagent/ops/`: doctor, metrics, release
  evidence, release manifest, batch, and trace replay commands.

## Console Scripts

Installed entry points:

```sh
kagent --version
kagent-batch /tmp/goals.jsonl /tmp/results.jsonl
kagent-doctor --production --require-runtime-provider
kagent-eval --list-cases
kagent-metrics /tmp/kagent-continuous.jsonl
kagent-release-evidence --help
kagent-release-manifest --help
kagent-serve --host 127.0.0.1 --port 8000
kagent-trace-prune /tmp/kagent-traces --max-age-days 7
kagent-trace-replay /tmp/kagent-traces/RUN_ID.json
```

## Release And Operations

Common local gates:

```sh
make check
make smoke-service
make readiness-audit
make production-approval-bundle
```

Release and rollout scripts:

- `scripts/production_readiness_audit.py`
- `scripts/staging_acceptance.sh`
- `scripts/observability_acceptance.sh`
- `scripts/internal_rollout_acceptance.py`
- `scripts/production_approval_bundle.sh`
- `scripts/smoke_real_llm_runtime.sh`

These scripts emit redacted evidence and are documented in
`docs/operations.md`, `docs/production-readiness.md`, and
`docs/internal-rollout.md`.

## Python API

Stable package-level imports are available for automation:

```python
from kagent import (
    FakeLLMProvider,
    evaluate_agent,
    preview_plan,
    registered_evaluation_cases,
    registered_tool_metadata,
    run_agent,
    run_runtime_agent,
    summarize_run,
)
```

Example deterministic runtime test:

```python
from kagent import FakeLLMProvider, run_runtime_agent

provider = FakeLLMProvider(
    '{"actions":[{"id":"step-1","tool":"note","input":{"text":"hello"}}]}'
)
result = run_runtime_agent("capture hello", provider=provider)
```

The package ships a `py.typed` marker for downstream type checkers.

## Documentation

- Architecture: `docs/architecture.md`
- Operations runbook: `docs/operations.md`
- Deployment guide: `docs/deployment.md`
- Internal rollout: `docs/internal-rollout.md`
- Production readiness: `docs/production-readiness.md`
- Internal client example: `examples/internal_runtime_client.py`
- Release notes: `CHANGELOG.md`

## Current Graph

```text
planner -> executor -> verifier -> END
                       verifier -> reflector -> executor
```

The deterministic graph retries failed verification through the reflector until
the step budget is exhausted. The runtime path uses bounded plan-act-observe
iterations with strict plan validation and policy-gated tool execution.
