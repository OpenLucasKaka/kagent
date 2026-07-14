import assert from "node:assert/strict";
import test from "node:test";

import {
  appRuntimeReducer,
  createAppRuntimeState,
} from "./app-state";

test("does not render failed run completion as Done", () => {
  const state = appRuntimeReducer(createAppRuntimeState(), {
    type: "runtime_event",
    channel: "run",
    event: {
      type: "run_completed",
      status: "failed",
      answer: "",
      payload: {
        error: "final_answer is required when actions is empty",
      },
    },
  });

  assert.equal(state.status, "error");
  assert.deepEqual(
    state.transcript.entries.map((entry) => [entry.role, entry.text]),
    [["system", "final_answer is required when actions is empty"]],
  );
});

test("tracks active run lifecycle and clears activity on terminal events", () => {
  let state = createAppRuntimeState();
  assert.equal(state.activity, null);

  state = appRuntimeReducer(state, { type: "submit", text: "Plan a trip", command: false });
  assert.equal(state.activity?.phase, "Preparing your request");

  state = appRuntimeReducer(state, {
    type: "runtime_event",
    channel: "run",
    event: { type: "run_started", goal: "Plan a trip", max_iterations: "5" },
  });
  assert.equal(state.activity?.phase, "Planning next steps");

  state = appRuntimeReducer(state, {
    type: "runtime_event",
    channel: "run",
    event: {
      type: "run_progress",
      event: {
        type: "tool_completed",
        presentation: { title: "Checked weather", detail: "Three cities" },
      },
    },
  });
  assert.equal(state.activity?.latestOutcome, "Checked weather · Three cities");
  assert.equal(state.transcript.entries.at(-1)?.title, "Checked weather");

  state = appRuntimeReducer(state, {
    type: "runtime_event",
    channel: "run",
    event: {
      type: "approval_required",
      action_id: "approve-1",
      title: "Book flight",
      reason: "This charges your card",
      target: "Shanghai → Tokyo",
    },
  });
  assert.equal(state.activity?.phase, "Waiting for your decision");
  assert.equal(state.activity?.detail, "Book flight · Shanghai → Tokyo");

  state = appRuntimeReducer(state, { type: "approval_response", approved: true });
  assert.equal(state.activity?.phase, "Continuing");
  state = appRuntimeReducer(state, { type: "cancel_requested", label: "Stopping" });
  assert.equal(state.activity?.phase, "Stopping");

  state = appRuntimeReducer(state, {
    type: "runtime_event",
    channel: "run",
    event: { type: "run_completed", status: "done", answer: "Done", payload: {} },
  });
  assert.equal(state.activity, null);

  state = appRuntimeReducer(state, { type: "submit", text: "Again", command: false });
  state = appRuntimeReducer(state, { type: "error", message: "Disconnected" });
  assert.equal(state.activity, null);
});

test("clears activity for each failed run terminal event", () => {
  const activeState = () => appRuntimeReducer(createAppRuntimeState(), {
    type: "submit",
    text: "Do work",
    command: false,
  });

  const failed = appRuntimeReducer(activeState(), {
    type: "runtime_event",
    channel: "run",
    event: { type: "run_failed", error_code: "failed", message: "Failed" },
  });
  assert.equal(failed.activity, null);

  const clientFailed = appRuntimeReducer(activeState(), {
    type: "runtime_event",
    channel: "run",
    event: { type: "client_failed", message: "Disconnected" },
  });
  assert.equal(clientFailed.activity, null);

  const invalidCompletion = appRuntimeReducer(activeState(), {
    type: "runtime_event",
    channel: "run",
    event: { type: "run_completed", status: "failed", answer: "", payload: {} },
  });
  assert.equal(invalidCompletion.activity, null);
});
