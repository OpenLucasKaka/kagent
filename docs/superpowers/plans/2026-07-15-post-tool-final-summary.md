# Post-tool Final Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Kagent generate its final response after tool observations are available instead of ending with a pre-tool transition message.

**Architecture:** Preserve the planner/executor loop and add a non-action final-response writer after successful action plans that contain a draft answer. Approval resumes with exhausted planner budget use the same writer, with a deterministic presentation-safe summary as fallback.

**Tech Stack:** Python 3.9+, LangGraph runtime, pytest

---

### Task 1: Lock the desired convergence behavior

**Files:**
- Modify: `tests/test_runtime.py`

- [ ] **Step 1: Replace the stale-answer test with a failing regression**

Use a sequential provider whose first response contains a successful `note`
action and `final_answer: "让我帮你记录"`, and whose second response is the
post-tool answer `已记录 hello。`.

Assert that:

```python
assert result["answer"] == "已记录 hello。"
assert result["iteration_count"] == "1"
assert len(provider.calls) == 2
assert "hello" in provider.calls[1]["user"]
assert len(result["observations"]) == 1
```

- [ ] **Step 2: Run the regression and verify RED**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_runtime.py::test_runtime_agent_synthesizes_final_answer_after_successful_actions
```

Expected: FAIL because the current runtime returns the first transition message
and calls the provider only once.

### Task 2: Change the runtime convergence rule

**Files:**
- Modify: `src/kagent/runtime/agent.py`
- Test: `tests/test_runtime.py`

- [ ] **Step 1: Clarify the planner contract**

Add planner instructions to omit `final_answer` while returning actions. Add a
separate final-response prompt that cannot request or repeat tool actions.

- [ ] **Step 2: Implement the minimal loop change**

After all actions succeed, do not assign the pre-tool draft to `answer`. Invoke
the final-response writer with completed observations when a draft exists or an
approved action has exhausted the resumed planner budget. If the writer cannot
produce text, derive a concise problem/action/result fallback from presentation
content and the current user message.

- [ ] **Step 3: Run the focused regression and verify GREEN**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_runtime.py::test_runtime_agent_synthesizes_final_answer_after_successful_actions
```

Expected: PASS.

### Task 3: Verify approval resume and regressions

**Files:**
- Modify only if a regression exposes a missing case: `tests/test_stdio_runtime.py`

- [ ] **Step 1: Run runtime and stdio suites**

Run:

```bash
.venv/bin/python -m pytest -q tests/test_runtime.py tests/test_stdio_runtime.py
```

Expected: all tests pass.

- [ ] **Step 2: Run the full Python suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Reinstall the local npm package and run a real conversation**

Run:

```bash
npm run build:cli
npm install -g .
kagent
```

Ask Kagent for today's date, approve the command, and verify that the activity
shows the command execution followed by a final answer containing the date rather
than “让我帮你查询”.
