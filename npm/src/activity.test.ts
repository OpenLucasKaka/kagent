import assert from "node:assert/strict";
import test from "node:test";

import {
  createRuntimeActivityState,
  reduceRuntimeActivity,
  toggleRuntimeActivity,
} from "./activity";

test("reduces the runtime activity lifecycle into safe user-facing labels", () => {
  let activity = createRuntimeActivityState();

  activity = reduceRuntimeActivity(activity, { type: "planner_started" });
  assert.equal(activity.phase, "Planning next steps");

  activity = reduceRuntimeActivity(activity, {
    type: "planner_completed",
    action_count: "1",
  });
  assert.equal(activity.phase, "Preparing 1 step");
  assert.equal(activity.completedCount, 0);

  activity = reduceRuntimeActivity(activity, {
    type: "tool_started",
    presentation: {
      title: "Creating Status report",
      detail: "Preparing an artifact",
    },
  });
  assert.equal(activity.phase, "Creating Status report");
  assert.equal(activity.detail, "Preparing an artifact");

  activity = reduceRuntimeActivity(activity, {
    type: "tool_completed",
    presentation: {
      title: "Created Status report",
      detail: "Report · Markdown",
    },
  });
  assert.equal(activity.phase, "Created Status report");
  assert.equal(activity.latestOutcome, "Created Status report · Report · Markdown");
  assert.equal(activity.completedCount, 1);

  activity = reduceRuntimeActivity(activity, { type: "answer_started" });
  assert.equal(activity.phase, "Writing the response");

  activity = reduceRuntimeActivity(activity, { type: "steering_applied" });
  assert.equal(activity.phase, "Updating direction");

  activity = reduceRuntimeActivity(activity, {
    type: "approval_required",
    title: "Open page",
    target: "https://example.test",
  });
  assert.equal(activity.phase, "Waiting for your decision");
  assert.equal(activity.detail, "Open page · https://example.test");
});

test("does not repeat identical planning records in the activity timeline", () => {
  let activity = createRuntimeActivityState();

  activity = reduceRuntimeActivity(activity, {
    type: "tool_started",
    presentation: { title: "Planning next steps" },
  });
  activity = reduceRuntimeActivity(activity, { type: "planner_started" });
  activity = reduceRuntimeActivity(activity, { type: "planner_started" });

  assert.deepEqual(activity.timeline, [
    { title: "Planning next steps", detail: "" },
  ]);
});

test("uses safe fallbacks without exposing malformed presentation or raw event data", () => {
  let activity = createRuntimeActivityState();
  const rawTool = "read_file /private/secret.txt";

  activity = reduceRuntimeActivity(activity, {
    type: "tool_started",
    tool: rawTool,
    presentation: { title: { unsafe: rawTool }, detail: [rawTool] },
  });
  assert.equal(activity.phase, "Working on the next step");
  assert.equal(activity.detail, "");
  assert.deepEqual(activity.timeline, [{ title: "Working on the next step", detail: "" }]);

  activity = reduceRuntimeActivity(activity, {
    type: "tool_completed",
    tool: rawTool,
    presentation: { title: [rawTool], detail: { value: rawTool } },
  });
  assert.equal(activity.phase, "Reviewing latest result");
  assert.equal(activity.detail, "");
  assert.equal(activity.latestOutcome, "Reviewing latest result");
  assert.equal(activity.completedCount, 1);
  assert.equal(JSON.stringify(activity), JSON.stringify(activity).replaceAll(rawTool, ""));
});

test("retains only the six newest safe activity records", () => {
  let activity = createRuntimeActivityState();
  for (let index = 1; index <= 7; index += 1) {
    activity = reduceRuntimeActivity(activity, {
      type: "tool_started",
      presentation: { title: `Step ${index}`, detail: `Detail ${index}` },
    });
  }

  assert.deepEqual(activity.timeline, [
    { title: "Step 2", detail: "Detail 2" },
    { title: "Step 3", detail: "Detail 3" },
    { title: "Step 4", detail: "Detail 4" },
    { title: "Step 5", detail: "Detail 5" },
    { title: "Step 6", detail: "Detail 6" },
    { title: "Step 7", detail: "Detail 7" },
  ]);
});

test("leaves unknown events unchanged and toggles only the expanded flag", () => {
  const activity = reduceRuntimeActivity(createRuntimeActivityState(), {
    type: "tool_started",
    presentation: { title: "Inspecting project", detail: "Reading a guide" },
  });

  assert.equal(reduceRuntimeActivity(activity, { type: "unrecognized" }), activity);

  const toggled = toggleRuntimeActivity(activity);
  assert.deepEqual(
    { ...toggled, expanded: activity.expanded },
    activity,
  );
  assert.equal(toggled.expanded, !activity.expanded);
});
