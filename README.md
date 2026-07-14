# kagent

Production-shaped LangGraph agent runtime for internal, non-coding workflows.

It provides two execution paths:

- deterministic graph runs for local tests, smoke checks, and regression checks;
- an agent runtime that plans with a configured LLM provider,
  executes policy-gated tools, records structured observations, and can replan
  after failures.

The project is intentionally conservative: bounded iterations, strict JSON
plan parsing, explicit tool schemas, approval gates for risky actions, compact
operator output, and redacted production evidence.

## Quick Start

npm install:

```sh
npm install -g @openlucaskaka/kagent@latest
kagent
```

The default `kagent` command opens an Ink-based terminal UI and keeps the
Python LangGraph runtime as the execution engine behind it. The first run
prepares a private Python runtime under your user cache, installs kagent there,
and then opens the terminal agent. If no provider is configured yet, kagent
starts a first-time setup flow. The setup first asks you to choose Qwen,
DeepSeek, Ollama, or OpenAI-compatible/custom from a provider menu, then asks
for that provider's Base URL, model, and API key. Without a home override, the
local provider config is stored at `~/.kagent/config/provider.json` with
owner-only permissions. Use `kagent --classic` to bypass the Ink UI and run the
Python CLI directly.

Published stable releases use the npm `latest` tag (`stable/latest` channel);
prereleases such as beta builds use the `next` tag (`beta/next` channel). Set
`KAGENT_UPDATE_CHANNEL=beta` or `next` to follow prereleases. Interactive TTY
launches check the selected registry channel at most once every 24 hours and
prompt before upgrading. Set `KAGENT_NO_SELF_UPDATE=1` to disable automatic
checks. Run `kagent update --check` for an immediate read-only check or
`kagent upgrade` to install the selected channel explicitly. Check metadata is
stored at `~/.kagent/cache/npm-self-update.json` by default.

The npm launcher supports macOS and Linux (platform identifiers `darwin` and `linux`)
and stores each immutable Python runtime under
`~/.kagent/cache/npm-python`. A new runtime is downloaded and
prepared only when the Python dependency or ABI identity changes; a package
release with unchanged dependencies and ABI reuses the existing runtime.

To reconfigure later:

```sh
kagent --configure
```

Environment variables still override the local config for CI or temporary
operator sessions: `KAGENT_LLM_PROVIDER`, `KAGENT_LLM_BASE_URL`,
`KAGENT_LLM_API_KEY`, and `KAGENT_LLM_MODEL`.

### User and project data

The following is the default layout under `~/.kagent`:

```text
~/.kagent/config/provider.json
~/.kagent/state/session-memory.json
~/.kagent/state/history
~/.kagent/state/pending-approvals/
~/.kagent/state/patches/
~/.kagent/cache/npm-python/
~/.kagent/cache/npm-self-update.json
~/.kagent/.migration-v1-complete
```

Set `KAGENT_HOME` to move that shared root. Existing explicit override
variables, such as `KAGENT_LLM_CONFIG_PATH`, `KAGENT_SESSION_MEMORY_PATH`,
`KAGENT_HISTORY_PATH`, `KAGENT_PENDING_APPROVAL_PATH`,
`KAGENT_PATCH_STATE_DIR`, and `KAGENT_NODE_VENV`, retain higher precedence than
`KAGENT_HOME`. The default is used only when neither an explicit override nor
`KAGENT_HOME` is set. `KAGENT_HOME` relocates the entire user-level layout:
config, state, cache, and migration marker all move beneath the resolved
`KAGENT_HOME` root.

On first use of the default home, Kagent safely copies durable provider and
state data from the former XDG locations. Existing destinations are never
overwritten, legacy sources remain untouched, owner-only permissions and
symlink checks are enforced, and disposable cache data is rebuilt under
`cache/npm-python` in the resolved root instead of migrated. XDG variables are legacy
migration sources, not current defaults. An explicit `KAGENT_HOME` skips legacy
discovery so a custom home cannot import unrelated state. The
`.migration-v1-complete` marker in the resolved root is written only after all
eligible durable data has migrated successfully; npm update metadata lives at
`cache/npm-self-update.json` beneath that root.

The project-local `$PWD/.kagent` directory remains separate from the resolved
user-level Kagent root (default `~/.kagent`): runtime workspaces and project
skills continue to live under `$PWD/.kagent/runtime-workspace` and
`$PWD/.kagent/skills`.

One-shot runs use the same command:

```sh
kagent "draft an internal rollout checklist"
```

Start the local HTTP service after npm installation:

```sh
kagent-serve --host 127.0.0.1 --port 8000
```

Local source checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
scripts/run_checks.sh
```

Start the LLM-backed terminal agent after setting provider environment
variables:

```sh
# Set KAGENT_LLM_PROVIDER, KAGENT_LLM_BASE_URL, KAGENT_LLM_API_KEY,
# and KAGENT_LLM_MODEL in your shell or secret manager.

kagent
```

Run a one-shot runtime goal through the same default agent path:

```sh
kagent "draft an internal rollout checklist"
```

Run the deterministic regression graph explicitly when you need local,
LLM-free checks:

```sh
.venv/bin/python -m kagent.cli --deterministic "calculate 2 + 3"
```

Inspect the default Codex-style runtime LangGraph topology:

```sh
kagent --runtime --graph
```

After package installation, the console entrypoint is the same daily-use
interface:

```sh
kagent
```

TTY sessions show live progress and a compact operator transcript by default.
During a runtime turn, a compact activity workspace shows the current
user-visible phase, elapsed time, latest safe outcome when space permits, and
the completed-step count. Final answers stream into one stable transcript entry
as provider chunks arrive.
The Ink editor supports wrapped Chinese and emoji input, pasted graphemes,
Backspace and forward Delete, Home/End, prompt history, and a responsive layout
tested at 40 and 100 columns. PageUp/PageDown browse older conversation pages
without moving the prompt cursor. Multiline paste keeps line breaks; use
Shift+Enter, Option+Enter, or Ctrl+J to insert a line break and Enter to run.
Type `/` to open the command palette, use Up/Down to select, and Tab to
complete. Ctrl-C cooperatively cancels an active run without restarting the
Python session. While kagent is working, the prompt remains editable and Enter
queues the latest additional instruction for the next planner or tool boundary;
Escape requests cancellation. Ctrl+O expands or collapses the safe activity
evidence while a turn is running; after a run, Ctrl+O continues to expand or
collapse the latest result with available content. Permission prompts
show the user-facing action and target while keeping internal tool identifiers
out of the normal transcript.
Completed file changes, artifacts, browser actions, HTTP fetches, workspace
diffs, and bounded command results appear as concise outcome lines without
internal tool names.

Use `/pwd`, `/cd PATH`, `/status`, `/config`, `/tools`, `/memory`,
`/compact-memory`, `/clear`, `/reset`, and `/help` in the Ink terminal. The
classic Python terminal additionally provides `/doctor`, `/json`, `/compact`,
`/last`, `/trace`, and `/save-trace PATH`. Unknown slash commands and known
commands with invalid arguments are handled locally with suggestions or usage
hints and are not sent to the model as goals.
Persisted session memory is owner-only on read and write,
uses `0700` parent directories, rejects symlink memory files or parent
directories, and redacts common API keys, bearer tokens, and URL credentials
before reusing memory in later turns or writing it to disk. Memory uses a v2
compact layout with durable summary, durable facts, open items, and recent
turns. Long sessions automatically compact older turns before they are reused
in prompts; `/compact-memory` forces compaction immediately and `/memory`
shows the current summary/facts/open-items/recent-turns view. The CLI
defaults to the runtime for both `kagent` and `kagent "goal"`; use
`--deterministic` only for the legacy regression graph. Runtime turns use three
planning iterations by default. Without a home override, TTY sessions persist
memory at `~/.kagent/state/session-memory.json`; set
`KAGENT_SESSION_MEMORY_PATH` to override that path or to an empty value to
disable default persistence. Without a home override, prompt history is stored
owner-only at `~/.kagent/state/history`; set `KAGENT_HISTORY_PATH`
to override it or to an empty value to disable persisted prompt history. Both
memory and prompt history redact common API keys, bearer tokens, and URL
credentials before writing to disk. Use `--max-iterations` to override the iteration
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
- opening local macOS applications by app name;
- approved bounded local shell commands for internal CLI checks, with
  destructive, secret-exposing, and network shell commands rejected;
- creating, updating, moving, and deleting workspace files through an audited
  `apply_patch` flow with transactional rollback and approval-gated undo/redo.
- maintaining versioned virtual-workspace assets with reviewed diff and
  approval-gated current/revision SHA-locked restore and redo.

Risky tools are policy-gated. Runs expose structured events, observations,
approval state, artifacts, and metrics so internal dashboards can inspect what
happened without reading raw traces by default. Runtime summaries include
compact fields such as `progress_event_count` for timeline-oriented UIs.
Interactive approvals accept `d` to inspect the pending action JSON before
answering `y` or `n`.

## Service

Start the local HTTP service:

```sh
kagent-serve --host 127.0.0.1 --port 8000
```

Useful endpoints include:

- `GET /health`, `HEAD /health`, `GET /ready`, `HEAD /ready`
- `GET /config`, `GET /version`, `GET /tools`, `GET /runtime/graph`, `GET /runtime/tools`
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
- `src/kagent/providers/`: provider detection, OpenAI-compatible protocol
  adapter, and fake provider test support.
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
kagent-trace-prune /tmp/kagent-traces --max-age-days 7 --runtime-only --fail-on-errors
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
