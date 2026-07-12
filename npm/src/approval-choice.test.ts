import assert from "node:assert/strict";
import test from "node:test";

import { resolveApprovalInput } from "./approval-choice";

test("moves approval focus with arrow keys", () => {
  assert.deepEqual(resolveApprovalInput("deny", "", "left"), {
    type: "select",
    choice: "allow",
  });
  assert.deepEqual(resolveApprovalInput("allow", "", "right"), {
    type: "select",
    choice: "deny",
  });
});

test("submits the focused approval choice with enter", () => {
  assert.deepEqual(resolveApprovalInput("allow", "", "enter"), {
    type: "submit",
    approved: true,
  });
  assert.deepEqual(resolveApprovalInput("deny", "", "return"), {
    type: "submit",
    approved: false,
  });
});

test("keeps direct approval and details shortcuts", () => {
  assert.deepEqual(resolveApprovalInput("deny", "y"), {
    type: "submit",
    approved: true,
  });
  assert.deepEqual(resolveApprovalInput("allow", "n"), {
    type: "submit",
    approved: false,
  });
  assert.deepEqual(resolveApprovalInput("deny", "d"), {
    type: "toggle_details",
  });
});
