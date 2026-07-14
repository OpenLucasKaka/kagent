# Runtime Activity Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Give active Ink terminal runs a compact, expandable workspace that explains current work, outcomes, progress, elapsed time, and approval state without exposing internal runtime data.

**Architecture:** Python emits a redacted presentation projection when a tool starts, matching the trust boundary used for completed tools. TypeScript reduces planner, tool, answer, and approval events into bounded temporary activity state. Ink renders it above the prompt, where Ctrl+O toggles active details during a run and preserves transcript-result behavior when idle.

**Tech Stack:** Python 3.9, pytest, TypeScript 5, React 18, Ink 5, Node built-in test runner.

---

## File structure

| File | Responsibility |
| --- | --- |
| \`src/kagent/runtime/presentation.py\` | Project a redacted tool-start description. |
| \`src/kagent/runtime/agent.py\` | Attach the start projection to \`tool_started\`. |
| \`tests/test_runtime_presentation.py\` | Test start projection and redaction. |
| \`npm/src/activity.ts\` | Define and reduce temporary active-run state. |
| \`npm/src/activity.test.ts\` | Test activity transitions and bounded history. |
| \`npm/src/app-state.ts\` | Own activity lifecycle and toggling. |
| \`npm/src/ui-components.tsx\` | Render and size the workspace. |
| \`npm/src/App.tsx\` | Render it and route contextual Ctrl+O. |
| \`README.md\` | Document the operator controls. |

### Task 1: Emit safe tool-start presentation

**Files:**
- Modify: \`src/kagent/runtime/presentation.py:10-32\`
- Modify: \`src/kagent/runtime/agent.py:1449-1457\`
- Test: \`tests/test_runtime_presentation.py:197-224\`

- [ ] **Step 1: Write the failing Python tests**

~~~
def test_projects_safe_tool_start_without_exposing_raw_input():
    presentation = project_runtime_start_presentation(
        "artifact",
        {"title": "Release sk-secret123", "content": "Bearer abcdef"},
    )

    assert presentation == {
        "title": "Creating Release [REDACTED]",
        "detail": "Preparing an artifact",
    }
    assert "artifact" not in json.dumps(presentation).lower()
    assert "Bearer" not in json.dumps(presentation)


def test_runtime_agent_emits_safe_start_presentation_only_when_available():
    provider = FakeLLMProvider(
        '{"actions":[{"id":"artifact-action-secret","tool":"artifact",'
        '"input":{"title":"Status report","content":"Ready"},"reason":"create"},'
        '{"id":"note-action-secret","tool":"note",'
        '"input":{"text":"internal note"},"reason":"capture"}],'
        '"final_answer":"done"}'
    )
    result = run_runtime_agent("prepare status", provider=provider)
    started = [event for event in result["progress_events"] if event["type"] == "tool_started"]

    assert started[0]["presentation"] == {
        "title": "Creating Status report",
        "detail": "Preparing an artifact",
    }
    assert "presentation" not in started[1]
    assert "artifact-action-secret" not in json.dumps(started[0]["presentation"])
~~~

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: \`pytest tests/test_runtime_presentation.py -q\`

Expected: FAIL during collection because \`project_runtime_start_presentation\` does not exist.

- [ ] **Step 3: Add the projection helper and attach it to the event**

In \`presentation.py\`, import \`Mapping\` and add this public helper before \`project_runtime_presentation\`:

~~~
def project_runtime_start_presentation(tool: str, input_value: Mapping[str, Any]) -> Dict[str, Any]:
    if not isinstance(input_value, Mapping):
        return {}
    if tool == "artifact":
        title = _string(input_value.get("title"))
        if title:
            return _presentation(f"Creating {title}", "Preparing an artifact")
    labels = {
        "apply_patch": ("Updating workspace files", "Preparing a reviewed change"),
        "workspace_diff": ("Inspecting workspace changes", "Preparing a safe comparison"),
        "workspace_restore": ("Restoring workspace asset", "Preparing a reviewed restore"),
        "open_url": ("Opening requested page", "Preparing a local browser action"),
        "open_app": ("Opening requested application", "Preparing a local application action"),
        "http_request": ("Fetching requested URL", "Preparing a network request"),
        "shell_command": ("Running approved command", "Preparing a bounded command"),
    }
    label = labels.get(tool)
    return _presentation(*label) if label else {}
~~~

Import it in \`agent.py\`; before \`_emit_runtime_progress(..., "tool_started", ...)\`, compute \`start_presentation = project_runtime_start_presentation(action.tool, resolved_input)\` and add \`presentation=start_presentation or None\`. Do not add raw input to the progress event.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run: \`pytest tests/test_runtime_presentation.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit the safe runtime contract**

Run: \`git add src/kagent/runtime/presentation.py src/kagent/runtime/agent.py tests/test_runtime_presentation.py && git commit -m "feat: present active runtime tool work safely"\`

### Task 2: Create the active-run reducer

**Files:**
- Create: \`npm/src/activity.ts\`
- Create: \`npm/src/activity.test.ts\`

- [ ] **Step 1: Write the failing reducer test**

~~~
let activity = createRuntimeActivityState();
activity = reduceRuntimeActivity(activity, {type: "planner_started"});
assert.equal(activity.phase, "Planning next steps");
activity = reduceRuntimeActivity(activity, {
  type: "tool_started",
  presentation: {title: "Creating Status report", detail: "Preparing an artifact"},
});
assert.equal(activity.detail, "Preparing an artifact");
activity = reduceRuntimeActivity(activity, {
  type: "tool_completed",
  presentation: {title: "Created Status report", detail: "Report · Markdown"},
});
assert.equal(activity.latestOutcome, "Created Status report · Report · Markdown");
assert.equal(activity.completedCount, 1);
activity = reduceRuntimeActivity(activity, {
  type: "approval_required", title: "Open page", target: "https://example.test",
});
assert.equal(activity.phase, "Waiting for your decision");
~~~

Also assert unknown presentation falls back to \`Working on the next step\`, timeline retention is six records, and \`toggleRuntimeActivity\` only toggles \`expanded\`.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: \`npm run build:cli && node --test npm/lib/activity.test.js\`

Expected: FAIL because \`npm/src/activity.ts\` does not exist.

- [ ] **Step 3: Implement the pure activity module**

Export \`RuntimeActivityState\`, \`createRuntimeActivityState\`, \`reduceRuntimeActivity\`, and \`toggleRuntimeActivity\`. The state contains \`phase\`, \`detail\`, \`latestOutcome\`, \`completedCount\`, \`timeline\`, and \`expanded\`. Consume only \`Record<string, unknown>\` and guard every string. Map \`planner_started\`, \`planner_completed\`, \`tool_started\`, \`tool_completed\`, \`answer_started\`, and \`steering_applied\`; append only safe title/detail records and keep the newest six. Unknown events return the current state unchanged.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run: \`npm run build:cli && node --test npm/lib/activity.test.js\`

Expected: PASS.

- [ ] **Step 5: Commit the activity reducer**

Run: \`git add npm/src/activity.ts npm/src/activity.test.ts && git commit -m "feat: model active runtime activity"\`

### Task 3: Integrate activity lifecycle and contextual control

**Files:**
- Modify: \`npm/src/app-state.ts:22-305\`
- Modify: \`npm/src/app-state.test.ts:1-28\`
- Modify: \`npm/src/App.tsx:265-300,615-720\`
- Test: \`npm/src/App.test.tsx:1-230\`

- [ ] **Step 1: Write failing reducer and app interaction tests**

Extend \`app-state.test.ts\` to assert that \`run_started\` creates activity, \`run_progress\` changes it, approval enters \`Waiting for your decision\`, and \`run_completed\`, \`run_failed\`, and \`error\` clear it. Add an App harness test that sends Ctrl+O after a \`tool_started\` progress event and asserts \`runtimeState.activity.expanded\` changes while no transcript entry changes.

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: \`npm run build:cli && node --test npm/lib/app-state.test.js npm/lib/App.test.js\`

Expected: FAIL because \`AppRuntimeState\` has no \`activity\` field.

- [ ] **Step 3: Wire activity through app state and input handling**

Add \`activity: RuntimeActivityState | null\` to \`AppRuntimeState\`.

- A non-command \`submit\` creates activity with phase \`Preparing your request\`.
- \`run_started\` creates a fresh state with phase \`Planning next steps\`.
- \`run_progress\` reduces \`event.event\` into the current activity and retains the existing transcript reducer call.
- \`approval_required\` reduces a record containing the approval title and target; approval response sets \`Continuing\` or \`Cancelling\`.
- Cancel requested sets \`Stopping\`.
- Terminal completion, failure, and \`error\` clear activity in the same returned state that updates the transcript.

Add an app action \`{ type: "activity_toggle" }\`. In \`App.tsx\`, route Ctrl+O to that action only when \`runtimeState.activity\` exists; otherwise keep the existing \`toggle_latest_result\` transcript action.

- [ ] **Step 4: Run the focused tests and confirm they pass**

Run: \`npm run build:cli && node --test npm/lib/app-state.test.js npm/lib/App.test.js\`

Expected: PASS.

- [ ] **Step 5: Commit lifecycle and keyboard behavior**

Run: \`git add npm/src/app-state.ts npm/src/app-state.test.ts npm/src/App.tsx npm/src/App.test.tsx && git commit -m "feat: surface active run lifecycle in the terminal"\`

### Task 4: Render and reserve the Runtime Activity Workspace

**Files:**
- Modify: \`npm/src/ui-components.tsx:77-158,654-677\`
- Modify: \`npm/src/ui-components.test.ts:1-129\`
- Modify: \`npm/src/App.tsx:619-720\`
- Test: \`tests/test_npm_package.py:117-235\`

- [ ] **Step 1: Write failing layout and render tests**

~~~
const activity = {
  phase: "Creating Status report",
  detail: "Preparing an artifact",
  latestOutcome: "Created draft · Markdown",
  completedCount: 2,
  timeline: [],
  expanded: false,
};
assert.equal(estimateRuntimeActivityRows(activity, 38, true), 3);
assert.equal(estimateRuntimeActivityRows({...activity, expanded: true}, 96, false), 6);
~~~

Extend the Python npm layout probe to pass \`activity\` at 40 and 100 columns, assert it reserves more rows than the same layout without activity, and assert \`reservedRows <= rows - 1\` in a 40×10 terminal.

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: \`npm run build:cli && node --test npm/lib/ui-components.test.js && pytest tests/test_npm_package.py -q\`

Expected: FAIL because the workspace exports and layout overlay are absent.

- [ ] **Step 3: Implement workspace rendering and responsive layout**

In \`ui-components.tsx\`, add \`activity?: RuntimeActivityState | null\` to \`createTerminalLayout\` overlays; export \`estimateRuntimeActivityRows\`; include activity rows in \`reservedRows\`; and export \`RuntimeActivityWorkspace\`. Render phase with spinner and elapsed time, detail, latest outcome, completed count, \`Ctrl+O details\`, and \`Esc stop\`. When expanded, render only the two newest timeline records. When vertical space is limited, omit the latest outcome before phase, approval, or prompt.

In \`App.tsx\`, render the workspace after \`MessageList\` and before \`ApprovalPanel\`. Render generic \`StatusLine\` only while no activity is active so provider startup behavior stays unchanged.

- [ ] **Step 4: Run the focused test and confirm it passes**

Run: \`npm run build:cli && node --test npm/lib/ui-components.test.js && pytest tests/test_npm_package.py -q\`

Expected: PASS.

- [ ] **Step 5: Commit the responsive Ink workspace**

Run: \`git add npm/src/ui-components.tsx npm/src/ui-components.test.ts npm/src/App.tsx tests/test_npm_package.py && git commit -m "feat: render expandable runtime activity workspace"\`

### Task 5: Document and verify the operator experience

**Files:**
- Modify: \`README.md:115-145\`
- Verify: \`tests/test_runtime_presentation.py\`, \`npm/src/*.test.ts\`, \`tests/test_npm_package.py\`, \`tests/\`

- [ ] **Step 1: Add the active-run workspace behavior to the README**

Replace the active-run sentence in the Ink terminal paragraph with:

~~~
While kagent is working, a compact activity workspace shows the current
user-facing phase, elapsed time, latest safe outcome, and completed-step count.
Press Ctrl+O during a run to expand or collapse its safe evidence; after a run,
Ctrl+O continues to expand or collapse the latest outcome. The prompt remains
editable and Enter queues the latest additional instruction for the next
planner or tool boundary; Escape requests cancellation.
~~~

- [ ] **Step 2: Run lint, focused tests, and the repository gate**

Run: \`ruff check src tests && pytest tests/test_runtime_presentation.py tests/test_npm_package.py -q && npm run test:cli && scripts/run_checks.sh\`

Expected: every command exits 0; npm runs \`activity.test.js\`; no test output contains a raw tool identifier or test secret.

- [ ] **Step 3: Inspect the final diff and status**

Run: \`git diff --check HEAD~5..HEAD && git status --short\`

Expected: no whitespace errors; only the unrelated pre-existing \`docs/superpowers/plans/2026-07-13-npm-update-channels.md\` may remain untracked.

- [ ] **Step 4: Commit documentation and final verification evidence**

Run: \`git add README.md && git commit -m "docs: explain active runtime workspace"\`

