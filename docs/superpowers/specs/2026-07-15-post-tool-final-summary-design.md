# Post-tool Final Summary Design

## Goal

After Kagent executes one or more tools, the conversation must not end with a
pre-execution transition such as “让我帮你查询”. The runtime must use the tool
observations to produce a final user-facing summary that states what was handled,
what was done, and the result.

## Current behavior

The planner may return actions and `final_answer` in the same plan. The runtime
executes the actions and then immediately accepts that `final_answer`. Because the
text was generated before the tool observations existed, it can only describe an
intention and cannot report the actual result.

## Required behavior

- Keep the existing live activity UI for planner and tool execution events.
- A plan containing actions cannot terminate the run with its own `final_answer`.
- When a plan contains actions and a draft `final_answer`, run a dedicated
  final-response writer after the actions. This writer receives observations but
  cannot execute actions.
- Plans without a draft answer may continue normal bounded replanning while
  iteration budget remains.
- The system prompt must tell the planner not to repeat completed actions and to
  summarize the problem, work, and result from previous observations.
- Tool failures retain the existing recovery and terminal failure behavior.
- An explicitly approved action that completes with no planner iteration left
  must still produce a final summary.
- If the final-response writer fails or returns no answer, produce a concise
  deterministic `problem / action / result` summary from presentation-safe tool
  output.
- When stdio adds compact session memory to the planner goal, finalization must
  use only the `Current user message` section.
- A finalizer response that still contains actions is an old planner draft even
  when it also contains `final_answer`; discard it and use the observation summary.
- Answers must not append unrelated prior tasks, generic capability menus, or
  invitations to ask for more help.

## Scope

The runtime convergence rule and its Python tests change. Ink transcript and
activity rendering do not need structural changes because they already display
progress events and the final `run_completed.answer` separately.

## Verification

Automated regressions cover a transition-style draft answer, approval resume with
no planner budget, finalizer failure fallback, and compact session memory. A real
stdio approval run must finish with the current problem, executed tool, and actual
tool result.
