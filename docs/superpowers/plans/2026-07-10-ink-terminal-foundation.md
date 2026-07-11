# Ink Terminal Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular, cancellation-safe, streaming Ink terminal foundation for production Kagent sessions.

**Architecture:** Split deterministic editor, transcript, and command behavior from the Ink composition root. Extend the JSONL stdio protocol so Python runs the active LangGraph call in a worker thread and accepts cooperative cancellation without restarting the process.

**Tech Stack:** TypeScript, React 18, Ink 5, Node.js, Python 3.9+, LangGraph, pytest, Ruff.

---

### Task 1: Extract and complete the editor model

**Files:**
- Create: `npm/src/editor.ts`
- Modify: `npm/src/App.tsx`
- Test: `tests/test_npm_package.py`

- [x] Add a Node behavioral test that imports editor functions and verifies
  grapheme insertion, left/right movement, Backspace, forward Delete, Home,
  End, and submitted-input history traversal.
- [x] Run `npm run build:cli && pytest tests/test_npm_package.py -k editor -q` and
  confirm the new expectations fail before implementation.
- [x] Move `EditorState`, segmentation, insertion, and movement into
  `npm/src/editor.ts`; add `deleteAtCursor`, `moveToBoundary`, and a pure
  `EditorHistory` transition function.
- [x] Update `App.tsx` to import the editor model and map Ink key events to the
  correct operation.
- [x] Re-run the focused build and tests, then commit as
  `refactor: extract terminal editor model`.

### Task 2: Add command discovery state

**Files:**
- Create: `npm/src/commands.ts`
- Modify: `npm/src/App.tsx`
- Test: `tests/test_npm_package.py`

- [x] Add behavioral tests for command filtering, stable selection, Up/Down
  navigation, and Tab completion.
- [x] Define one typed command catalog containing `/help`, `/status`, `/config`,
  `/tools`, `/memory`, `/compact-memory`, `/clear`, `/reset`, `/cwd`, and
  `/export-trace` with user-facing descriptions only.
- [x] Add pure command-menu state transitions and wire them into the input
  handler without exposing runtime tool identifiers.
- [x] Verify build and focused tests, then commit as
  `feat: add terminal command palette`.

### Task 3: Build the transcript reducer and viewport

**Files:**
- Create: `npm/src/transcript.ts`
- Modify: `npm/src/App.tsx`
- Test: `tests/test_npm_package.py`

- [x] Add tests proving streamed deltas update one assistant message, final
  completion does not duplicate it, cancellation is represented distinctly,
  and viewport selection preserves the newest complete message.
- [x] Implement typed transcript entries with stable IDs and pure reducers for
  user submission, command results, runtime progress, final completion, and
  errors.
- [x] Add bounded transcript retention and terminal-height-aware viewport
  selection with conservative row estimation for wide Unicode text.
- [x] Replace direct `setMessages` branches in `App.tsx` with reducer actions.
- [x] Verify build and focused tests, then commit as
  `refactor: add terminal transcript model`.

### Task 4: Add cooperative stdio cancellation

**Files:**
- Modify: `src/kagent/cli/stdio_runtime.py`
- Modify: `npm/src/protocol.ts`
- Modify: `npm/src/runtime-client.ts`
- Test: `tests/test_stdio_runtime.py`
- Test: `tests/test_npm_package.py`

- [x] Add a Python protocol test using a blocking fake runtime and prove a
  `cancel_request` is handled before the worker returns.
- [x] Add a Node/Python integration test proving cancellation emits
  `run_cancel_requested`, completes with `status=cancelled`, keeps the same
  child process, and permits a subsequent run.
- [x] Introduce a locked stdout emitter and an active-run record containing the
  worker thread and `RuntimeCancellationToken`.
- [x] Move only run and approved-resume execution to worker threads; keep state
  mutation and request validation synchronized in the session.
- [x] Add typed cancel request/event protocol definitions and change
  `RuntimeSessionClient.cancel()` to send the request instead of restarting.
- [x] Verify `pytest tests/test_stdio_runtime.py tests/test_npm_package.py -q`
  and `npm run check`, then commit as
  `feat: cooperatively cancel terminal runs`.

### Task 5: Split visual components and render streaming state

**Files:**
- Create: `npm/src/ui-components.tsx`
- Modify: `npm/src/App.tsx`
- Test: `tests/test_npm_package.py`

- [x] Add Ink render tests for 40-column and 100-column layouts containing long
  Chinese input, streamed output, command suggestions, and approval details.
- [x] Extract banner, transcript, status line, approval prompt, command menu,
  provider setup, and prompt components into `ui-components.tsx`.
- [x] Keep the prompt and status regions outside the transcript viewport and
  render `Cancelling` separately from `Thinking`.
- [x] Use restrained Claude Code-style hierarchy: compact product identity,
  low-noise status, visible user/assistant roles, and details only on demand.
- [x] Verify build and render tests, then commit as
  `refactor: modularize ink terminal views`.

### Task 6: Harden runtime recovery and diagnostics

**Files:**
- Modify: `npm/src/runtime-client.ts`
- Modify: `npm/src/App.tsx`
- Modify: `npm/src/protocol.ts`
- Test: `tests/test_npm_package.py`

- [x] Add tests for child failure while idle, child failure during a run, one
  controlled restart, and preserved UI transcript after restart.
- [x] Separate recoverable runtime lifecycle failures from request failures and
  emit a typed restart lifecycle event.
- [x] Prevent restart loops with a single-attempt guard and show a concise user
  message with a debug hint rather than raw stderr.
- [x] Verify focused tests and commit as
  `fix: recover terminal runtime sessions safely`.

### Task 7: Documentation and release verification

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/operations.md`
- Modify: `docs/iteration_log.md`

- [x] Document the Ink/Python process boundary, cooperative cancellation,
  streaming transcript, command palette, and classic fallback.
- [x] Run `npm run check` and focused Python/Node tests.
- [x] Run `ruff check src tests` and `git diff --check`.
- [x] Run the complete `scripts/run_checks.sh` gate and inspect all output.
- [x] Run a real PTY smoke session at narrow and normal widths, then commit as
  `docs: document terminal runtime foundation`.

## Self-review

- Every design goal maps to Tasks 1-7.
- Cancellation includes protocol, Python concurrency, Node client behavior,
  integration tests, and UI state.
- Streaming includes event reduction, final de-duplication, viewport behavior,
  and render coverage.
- No task requires secrets, provider network calls, or coding-specific tools.
- The plan contains no deferred placeholders; later Claude Code-style features
  remain separate, explicit follow-on phases rather than hidden scope.
