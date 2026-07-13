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
