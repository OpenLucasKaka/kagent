# Ink Terminal Foundation Design

## Context

Before this foundation was implemented, most Ink behavior lived in one
`npm/src/App.tsx` file and Ctrl-C cancellation terminated the Python child.
That baseline lost runtime continuity, mixed pure editor behavior with process
lifecycle state, and made narrow-terminal regressions difficult to isolate.

The implemented foundation now separates editor, command, transcript,
responsive view, protocol, and child-process responsibilities. The Python
stdio runtime accepts cancellation while an agent worker is active, flushes
terminal events before declaring the worker idle, and keeps the same process
available for the next turn.

This design is the first sub-project in the broader Claude Code-style Kagent
experience. Later phases will add richer permission modes, session selection,
task views, extensibility, and background execution on top of these boundaries.

## Implementation status

The foundation was completed across commits `393a775` through `cdd8a8c`:

- grapheme-safe editor extraction and terminal input decoding;
- command palette and transcript reducers;
- cooperative Python/Node cancellation;
- responsive Ink components and real 40/100-column frame tests;
- one-attempt Python child crash recovery with transcript preservation;
- terminal-event shutdown ordering and quiet npm Python bootstrap.

This is a verified foundation, not a claim of complete Claude Code feature
parity. Session browsing, background jobs, plugin UX, richer permission modes,
and terminal scrollback remain separate follow-on work.

## Goals

1. Give the Ink UI explicit, testable state boundaries.
2. Preserve one Python runtime process and one conversation across normal runs.
3. Implement cooperative cancellation through the stdio protocol.
4. Render streamed answer deltas in one in-progress assistant message.
5. Support Unicode-safe editing, distinct Backspace/Delete behavior, command
   history, and an interactive slash-command menu.
6. Keep the input and current status visible when transcripts become long.
7. Replace source-string assertions with behavioral TypeScript and protocol
   tests for the new foundations.

## Non-goals

- Pixel-copying Claude Code branding or proprietary visuals.
- Adding coding-specific tools to this non-coding agent.
- Implementing remote multi-user session selection in this phase.
- Replacing the existing LangGraph runtime or provider abstraction.

## Architecture

### UI state

`App.tsx` remains the composition root only. Pure state and editing behavior
move into focused modules:

- `npm/src/editor.ts`: grapheme-aware cursor movement, Backspace, Delete,
  history traversal, and input insertion.
- `npm/src/transcript.ts`: transcript message types, streaming-message updates,
  bounded viewport selection, and runtime-event reduction.
- `npm/src/ui-components.tsx`: banner, transcript, status, approval, command
  menu, and prompt rendering.
- `npm/src/commands.ts`: slash-command catalog, filtering, and selection.

The application owns only lifecycle state and delegates deterministic state
transitions to these modules. This makes input and transcript behavior
testable without spawning a real terminal.

### Stdio runtime protocol

The protocol adds a `cancel_request` request and a `run_cancel_requested`
acknowledgement event. The Python stdio session runs an active agent call in a
worker thread while the main thread continues reading JSONL requests.

Each active run owns a `RuntimeCancellationToken`. A cancel request sets that
token instead of terminating the process. The worker emits the normal
`run_completed` event with status `cancelled` when the runtime reaches a
cancellation boundary. Provider configuration, session commands, and new runs
remain rejected while an active run is finishing.

All writes to stdout pass through one lock so JSONL events never interleave.
Session memory and pending approval state remain owned by the stdio session.

### Streaming transcript

`answer_started` creates one transient assistant message. Every `answer_delta`
appends to that message. `answer_completed` marks it complete. The final
`run_completed` event updates the same message rather than appending a duplicate
answer.

The UI renders a viewport derived from terminal height. The prompt, status, and
approval regions are outside the transcript viewport and therefore remain
visible. Older messages stay in application state up to a documented bounded
limit and can be revisited in a later scrollback phase.

### Input and command interaction

The editor uses grapheme indices rather than UTF-16 offsets. Backspace removes
the grapheme before the cursor; Delete removes the grapheme at the cursor.
Up/Down navigate submitted input history when the command menu is closed.

Typing `/` opens a filtered command menu. Up/Down changes the selected command,
Tab fills it into the editor, and Enter executes a complete selected command.
The menu is data-driven from a command catalog so help text and interaction do
not drift.

### Cancellation semantics

Ctrl-C during a run sends one cooperative cancellation request and changes the
UI status to `Cancelling`. Repeated Ctrl-C requests remain cooperative and do
not kill the child process. Ctrl-C while idle exits. Ctrl-C at an approval
prompt denies the pending action. Ctrl-C during provider setup exits, except
while settings are being saved, where it cancels and returns to the previous
setup stage.

## Error handling

- Invalid JSONL remains a protocol error without terminating the session.
- Duplicate cancel requests reuse the active token and cannot interleave JSONL
  output.
- Cancel with no active run returns a typed failure event.
- Worker exceptions are converted to `run_failed`; the failure event is flushed
  before active-run state is cleared.
- A child-process crash produces a visible system message and one controlled
  restart; it must not silently erase transcript state.
- Provider secrets never enter transcript messages, protocol diagnostics, or
  test snapshots.

## Testing

1. Pure Node tests cover Unicode editing, Delete versus Backspace, history,
   command filtering, streaming reduction, and viewport selection.
2. Python stdio tests prove the main loop accepts cancellation during an active
   run and emits a terminal cancelled result without process restart.
3. Node/Python integration tests prove one child session survives cancellation
   and can execute a subsequent request.
4. Ink render tests cover narrow terminals, long Chinese input, long answers,
   approval layout, and command-menu layout.
5. Existing full Python, Ruff, npm, wheel, smoke, and production-readiness
   checks remain release gates.

## Acceptance criteria

- `App.tsx` is a composition layer rather than the owner of pure editor and
  transcript algorithms.
- Ctrl-C cancellation does not restart the Python process or lose memory.
- Streaming output appears incrementally and is not duplicated on completion.
- Long Unicode input remains editable at terminal widths down to 40 columns.
- Slash commands are discoverable without printing internal tool names.
- Focused tests and the repository's complete `scripts/run_checks.sh` pass.
