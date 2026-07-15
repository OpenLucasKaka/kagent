"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const activity_1 = require("./activity");
(0, node_test_1.default)("reduces the runtime activity lifecycle into safe user-facing labels", () => {
    let activity = (0, activity_1.createRuntimeActivityState)();
    activity = (0, activity_1.reduceRuntimeActivity)(activity, { type: "planner_started" });
    strict_1.default.equal(activity.phase, "Planning next steps");
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "planner_completed",
        action_count: "1",
    });
    strict_1.default.equal(activity.phase, "Preparing 1 step");
    strict_1.default.equal(activity.completedCount, 0);
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "tool_started",
        presentation: {
            title: "Creating Status report",
            detail: "Preparing an artifact",
        },
    });
    strict_1.default.equal(activity.phase, "Creating Status report");
    strict_1.default.equal(activity.detail, "Preparing an artifact");
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "tool_completed",
        presentation: {
            title: "Created Status report",
            detail: "Report · Markdown",
        },
    });
    strict_1.default.equal(activity.phase, "Created Status report");
    strict_1.default.equal(activity.latestOutcome, "Created Status report · Report · Markdown");
    strict_1.default.equal(activity.completedCount, 1);
    activity = (0, activity_1.reduceRuntimeActivity)(activity, { type: "answer_started" });
    strict_1.default.equal(activity.phase, "Writing the response");
    activity = (0, activity_1.reduceRuntimeActivity)(activity, { type: "steering_applied" });
    strict_1.default.equal(activity.phase, "Updating direction");
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "approval_required",
        title: "Open page",
        target: "https://example.test",
    });
    strict_1.default.equal(activity.phase, "Waiting for your decision");
    strict_1.default.equal(activity.detail, "Open page · https://example.test");
});
(0, node_test_1.default)("does not repeat identical planning records in the activity timeline", () => {
    let activity = (0, activity_1.createRuntimeActivityState)();
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "tool_started",
        presentation: { title: "Planning next steps" },
    });
    activity = (0, activity_1.reduceRuntimeActivity)(activity, { type: "planner_started" });
    activity = (0, activity_1.reduceRuntimeActivity)(activity, { type: "planner_started" });
    strict_1.default.deepEqual(activity.timeline, [
        { title: "Planning next steps", detail: "" },
    ]);
});
(0, node_test_1.default)("uses safe fallbacks without exposing malformed presentation or raw event data", () => {
    let activity = (0, activity_1.createRuntimeActivityState)();
    const rawTool = "read_file /private/secret.txt";
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "tool_started",
        tool: rawTool,
        presentation: { title: { unsafe: rawTool }, detail: [rawTool] },
    });
    strict_1.default.equal(activity.phase, "Working on the next step");
    strict_1.default.equal(activity.detail, "");
    strict_1.default.deepEqual(activity.timeline, [{ title: "Working on the next step", detail: "" }]);
    activity = (0, activity_1.reduceRuntimeActivity)(activity, {
        type: "tool_completed",
        tool: rawTool,
        presentation: { title: [rawTool], detail: { value: rawTool } },
    });
    strict_1.default.equal(activity.phase, "Reviewing latest result");
    strict_1.default.equal(activity.detail, "");
    strict_1.default.equal(activity.latestOutcome, "Reviewing latest result");
    strict_1.default.equal(activity.completedCount, 1);
    strict_1.default.equal(JSON.stringify(activity), JSON.stringify(activity).replaceAll(rawTool, ""));
});
(0, node_test_1.default)("retains only the six newest safe activity records", () => {
    let activity = (0, activity_1.createRuntimeActivityState)();
    for (let index = 1; index <= 7; index += 1) {
        activity = (0, activity_1.reduceRuntimeActivity)(activity, {
            type: "tool_started",
            presentation: { title: `Step ${index}`, detail: `Detail ${index}` },
        });
    }
    strict_1.default.deepEqual(activity.timeline, [
        { title: "Step 2", detail: "Detail 2" },
        { title: "Step 3", detail: "Detail 3" },
        { title: "Step 4", detail: "Detail 4" },
        { title: "Step 5", detail: "Detail 5" },
        { title: "Step 6", detail: "Detail 6" },
        { title: "Step 7", detail: "Detail 7" },
    ]);
});
(0, node_test_1.default)("leaves unknown events unchanged and toggles only the expanded flag", () => {
    const activity = (0, activity_1.reduceRuntimeActivity)((0, activity_1.createRuntimeActivityState)(), {
        type: "tool_started",
        presentation: { title: "Inspecting project", detail: "Reading a guide" },
    });
    strict_1.default.equal((0, activity_1.reduceRuntimeActivity)(activity, { type: "unrecognized" }), activity);
    const toggled = (0, activity_1.toggleRuntimeActivity)(activity);
    strict_1.default.deepEqual({ ...toggled, expanded: activity.expanded }, activity);
    strict_1.default.equal(toggled.expanded, !activity.expanded);
});
