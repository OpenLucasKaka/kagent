# Production Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the LangGraph self-correcting agent into a readable,
production-oriented library and CLI.

**Architecture:** Keep the existing deterministic LangGraph loop. Add
observability and automation semantics at the public boundaries first, then
refactor internals only where tests already protect behavior.

**Tech Stack:** Python 3.9, LangGraph, argparse, pytest, shell smoke scripts.

---

### Task 1: Run Metadata

**Files:**
- Modify: `src/self_correcting_langgraph_agent/agent.py`
- Modify: `src/self_correcting_langgraph_agent/summary.py`
- Test: `tests/test_agent_graph.py`
- Test: `tests/test_summary.py`

- [ ] Write failing tests asserting `run_agent()` output includes `run_id`,
  `started_at`, `completed_at`, and `duration_seconds`.
- [ ] Run the focused tests and confirm missing metadata failures.
- [ ] Add metadata creation in `run_agent()` around graph invocation.
- [ ] Add metadata to compact summaries.
- [ ] Run focused tests, then `scripts/run_checks.sh`.

### Task 2: Structured Tool Metadata

**Files:**
- Modify: `src/self_correcting_langgraph_agent/tools.py`
- Modify: `src/self_correcting_langgraph_agent/cli.py`
- Modify: `README.md`
- Test: `tests/test_tools.py`
- Test: `tests/test_cli.py`

- [ ] Write failing tests for `registered_tool_metadata()` with name,
  command, description, and example.
- [ ] Write failing CLI test for `--list-tools --verbose`.
- [ ] Extend `ToolSpec` with metadata fields and expose a metadata function.
- [ ] Keep existing `--list-tools` output backward-compatible by default.
- [ ] Run focused tests, then `scripts/run_checks.sh`.

### Task 3: CLI Failure Exit Semantics

**Files:**
- Modify: `src/self_correcting_langgraph_agent/cli.py`
- Modify: `README.md`
- Test: `tests/test_cli.py`

- [ ] Write failing test for `--fail-on-agent-failure`, using an unsupported
  plan that prints JSON and exits `1`.
- [ ] Implement opt-in exit behavior after JSON output.
- [ ] Document shell automation usage.
- [ ] Run focused tests, then `scripts/run_checks.sh`.

### Task 4: Evaluator Filtering

**Files:**
- Modify: `src/self_correcting_langgraph_agent/evaluator.py`
- Modify: `pyproject.toml` only if entry points need changes
- Modify: `README.md`
- Test: `tests/test_evaluator.py`

- [ ] Write failing test for category filtering, e.g. recovery-only cases.
- [ ] Write failing CLI/module test for `--category recovery`.
- [ ] Add optional filters to `evaluate_agent()`.
- [ ] Preserve full evaluator defaults and metrics compatibility.
- [ ] Run focused tests, then `scripts/run_checks.sh`.

### Task 5: Final Readability Pass

**Files:**
- Modify: modules touched during Tasks 1-4 only
- Modify: `docs/iteration_log.md`

- [ ] Re-read touched modules and remove duplication introduced by the tasks.
- [ ] Update `docs/iteration_log.md` with verified changes.
- [ ] Run `scripts/run_checks.sh`.
- [ ] Check `/tmp/self-correcting-agent-three-hour.jsonl` with metrics CLI.
