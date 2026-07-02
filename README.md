# Self-Correcting LangGraph Agent

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
.venv/bin/python -m self_correcting_langgraph_agent.cli "calculate 2 + 3"
```

Run the LLM-backed runtime after setting provider environment variables:

```sh
export SELF_CORRECTING_LLM_BASE_URL="$PROVIDER_BASE_URL"
export SELF_CORRECTING_LLM_API_KEY="$PROVIDER_API_KEY"
export SELF_CORRECTING_LLM_MODEL="$PROVIDER_MODEL"

.venv/bin/python -m self_correcting_langgraph_agent.cli \
  "draft an internal rollout checklist" \
  --runtime \
  --max-iterations 3
```

Start the interactive terminal runtime:

```sh
.venv/bin/python -m self_correcting_langgraph_agent.cli \
  --runtime \
  --interactive \
  --max-iterations 3 \
  --session-memory PATH
```

TTY sessions show live progress and a compact operator transcript by default.
Use `/json`, `/compact`, `/last`, `/trace`, `/memory`, `/clear`, and `/help`
inside the shell. Add `--runtime-plan` for deterministic runtime tests and
`--interactive-json` when you need full traces. Runtime and service config
integers must be JSON integers, not strings or booleans.

## What It Can Do

The runtime currently includes tools for:

- notes and structured artifacts;
- task lists, rubrics, text transforms, and decision matrices;
- approved HTTP GET requests with SSRF protections;
- opening URLs in the local browser;
- creating workspace files through an audited `apply_patch` flow.

Risky tools are policy-gated. Runs expose structured events, observations,
approval state, artifacts, and metrics so internal dashboards can inspect what
happened without reading raw traces by default. Runtime summaries include
compact fields such as `progress_event_count` for timeline-oriented UIs.

## Service

Start the local HTTP service:

```sh
self-correcting-agent-serve --host 127.0.0.1 --port 8000
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

- `src/self_correcting_langgraph_agent/core/`: deterministic LangGraph loop.
- `src/self_correcting_langgraph_agent/runtime/`: LLM runtime, policies, tools,
  and typed runtime data.
- `src/self_correcting_langgraph_agent/service/`: stdlib HTTP service, routing,
  status, approvals, resume/cancel, trace store, and transport helpers.
- `src/self_correcting_langgraph_agent/cli/`: command line and interactive
  terminal UI.
- `src/self_correcting_langgraph_agent/providers/`: OpenAI-compatible provider
  and fake provider test support.
- `src/self_correcting_langgraph_agent/eval/`: evaluation cases and runner.
- `src/self_correcting_langgraph_agent/ops/`: doctor, metrics, release
  evidence, release manifest, batch, and trace replay commands.

## Console Scripts

Installed entry points:

```sh
self-correcting-agent --version
self-correcting-agent-batch /tmp/goals.jsonl /tmp/results.jsonl
self-correcting-agent-doctor --production --require-runtime-provider
self-correcting-agent-eval --list-cases
self-correcting-agent-metrics /tmp/self-correcting-agent-continuous.jsonl
self-correcting-agent-release-evidence --help
self-correcting-agent-release-manifest --help
self-correcting-agent-serve --host 127.0.0.1 --port 8000
self-correcting-agent-trace-prune /tmp/self-correcting-agent-traces --max-age-days 7
self-correcting-agent-trace-replay /tmp/self-correcting-agent-traces/RUN_ID.json
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
from self_correcting_langgraph_agent import (
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
from self_correcting_langgraph_agent import FakeLLMProvider, run_runtime_agent

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
