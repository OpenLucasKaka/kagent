"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const ui_components_1 = require("./ui-components");
const activity_1 = require("./activity");
const terminal_width_1 = require("./terminal-width");
(0, node_test_1.default)("does not reserve session header rows after the intro has been shown", () => {
    const withIntroOverlay = {
        approval: false,
        commandMenu: false,
        introVisible: true,
        prompt: "",
        promptCursor: 0,
    };
    const withoutIntroOverlay = {
        approval: false,
        commandMenu: false,
        introVisible: false,
        prompt: "",
        promptCursor: 0,
    };
    const withIntro = (0, ui_components_1.createTerminalLayout)(100, 30, {
        ...withIntroOverlay,
    });
    const withoutIntro = (0, ui_components_1.createTerminalLayout)(100, 30, {
        ...withoutIntroOverlay,
    });
    strict_1.default.equal(withIntro.reservedRows - withoutIntro.reservedRows, 3);
});
(0, node_test_1.default)("reserves the compact and wide runtime activity workspace heights", () => {
    const activity = {
        ...(0, activity_1.createRuntimeActivityState)(),
        phase: "Creating the release notes",
        detail: "Summarising the completed work",
        latestOutcome: "Updated docs/release-notes.md",
        completedCount: 2,
    };
    strict_1.default.equal((0, ui_components_1.estimateRuntimeActivityRows)(activity, 40, true), 3);
    strict_1.default.equal((0, ui_components_1.estimateRuntimeActivityRows)(activity, 56, false), 4);
    strict_1.default.equal((0, ui_components_1.estimateRuntimeActivityRows)(activity, 100, false), 4);
    strict_1.default.equal((0, ui_components_1.estimateRuntimeActivityRows)({
        ...activity,
        expanded: true,
        timeline: [
            { title: "Checked changelog", detail: "README.md" },
            { title: "Wrote release notes", detail: "docs/release-notes.md" },
        ],
    }, 100, false), 6);
});
(0, node_test_1.default)("limits runtime activity rows before approval and prompt space", () => {
    const activity = {
        ...(0, activity_1.createRuntimeActivityState)(),
        phase: "Writing response",
        detail: "A detailed update",
        latestOutcome: "Updated status",
        completedCount: 2,
    };
    const layout = (0, ui_components_1.createTerminalLayout)(40, 10, {
        approval: true,
        commandMenu: false,
        activity,
        prompt: "",
        promptCursor: 0,
    });
    strict_1.default.equal(layout.activityRowLimit, 1);
    strict_1.default.ok(layout.reservedRows <= 9);
    strict_1.default.ok(layout.promptRowLimit >= 1);
});
(0, node_test_1.default)("keeps long CJK and ASCII runtime phases visible within their constrained row budgets", () => {
    for (const [phase, visible] of [
        ["正在整理一份非常长的运行状态说明，确保审批和输入区域始终可见", "正在整理"],
        ["Preparing a detailed runtime status update while approval and prompt remain visible", "Preparing"],
    ]) {
        const activity = { ...(0, activity_1.createRuntimeActivityState)(), phase };
        const layout = (0, ui_components_1.createTerminalLayout)(40, 10, {
            approval: true,
            commandMenu: false,
            activity,
            prompt: "",
            promptCursor: 0,
        });
        const text = [];
        const React = {
            createElement(type, props, ...children) {
                if (typeof type === "function") {
                    return type({
                        ...(props && typeof props === "object" ? props : {}),
                        children,
                    });
                }
                text.push(...children.filter((child) => typeof child === "string"));
                return { type, props, children };
            },
        };
        (0, ui_components_1.RuntimeActivityWorkspace)({
            React: React,
            Box: "Box",
            Text: "Text",
            activity,
            compact: true,
            frame: 0,
            elapsedSeconds: 4,
            maxRows: layout.activityRowLimit ?? 0,
            columns: layout.columns,
        });
        const rendered = text.join("");
        strict_1.default.match(rendered, new RegExp(visible));
        strict_1.default.ok((0, terminal_width_1.estimateTextRows)(rendered, layout.columns) <= layout.activityRowLimit);
    }
});
(0, node_test_1.default)("renders runtime activity details and only the newest expanded timeline entries", () => {
    const activity = {
        ...(0, activity_1.createRuntimeActivityState)(),
        phase: "Writing response",
        detail: "Answering in Chinese: 正在整理",
        latestOutcome: "Created summary",
        completedCount: 3,
        expanded: true,
        timeline: [
            { title: "Old entry", detail: "hidden" },
            { title: "Recent entry", detail: "one" },
            { title: "Newest entry", detail: "two" },
        ],
    };
    const text = [];
    const React = {
        createElement(type, props, ...children) {
            if (typeof type === "function") {
                return type({
                    ...(props && typeof props === "object" ? props : {}),
                    children,
                });
            }
            text.push(...children.filter((child) => typeof child === "string"));
            return { type, props, children };
        },
    };
    (0, ui_components_1.RuntimeActivityWorkspace)({
        React: React,
        Box: "Box",
        Text: "Text",
        activity,
        compact: false,
        frame: 0,
        elapsedSeconds: 4,
        maxRows: 6,
    });
    const rendered = text.join(" ");
    strict_1.default.match(rendered, /Writing response · 4s/);
    strict_1.default.match(rendered, /Answering in Chinese: 正在整理/);
    strict_1.default.match(rendered, /Created summary/);
    strict_1.default.match(rendered, /3 completed · Ctrl\+O details · Esc stop/);
    strict_1.default.doesNotMatch(rendered, /Old entry/);
    strict_1.default.match(rendered, /Recent entry · one/);
    strict_1.default.match(rendered, /Newest entry · two/);
});
(0, node_test_1.default)("positions the real terminal cursor on the empty prompt input cell", () => {
    strict_1.default.deepEqual((0, ui_components_1.createPromptTerminalCursorControl)({
        input: "",
        cursor: 0,
        columns: 80,
        maxRows: 6,
        horizontalPadding: 1,
    }), {
        position: "\u001b[?25h\u001b[1A\u001b[3C",
        restore: "\r\u001b[1B",
    });
});
(0, node_test_1.default)("positions the real terminal cursor on wrapped prompt input", () => {
    strict_1.default.deepEqual((0, ui_components_1.createPromptTerminalCursorControl)({
        input: "abcde",
        cursor: 5,
        columns: 5,
        maxRows: 6,
        horizontalPadding: 0,
    }), {
        position: "\u001b[?25h\u001b[1A\u001b[2C",
        restore: "\r\u001b[1B",
    });
});
(0, node_test_1.default)("restores from an upper prompt cursor row before the next Ink render", () => {
    strict_1.default.deepEqual((0, ui_components_1.createPromptTerminalCursorControl)({
        input: "abcdef",
        cursor: 2,
        columns: 5,
        maxRows: 6,
        horizontalPadding: 0,
    }), {
        position: "\u001b[?25h\u001b[2A\u001b[4C",
        restore: "\r\u001b[2B",
    });
});
(0, node_test_1.default)("hides the empty prompt placeholder when IME-safe rendering is enabled", () => {
    strict_1.default.equal((0, ui_components_1.shouldRenderPromptPlaceholder)({
        input: "",
        disabled: false,
        imeSafe: true,
    }), false);
});
(0, node_test_1.default)("keeps the empty prompt placeholder for normal prompts", () => {
    strict_1.default.equal((0, ui_components_1.shouldRenderPromptPlaceholder)({
        input: "",
        disabled: false,
        imeSafe: false,
    }), true);
});
(0, node_test_1.default)("does not render the Ink prompt cursor when IME-safe terminal cursor sync is active", () => {
    strict_1.default.equal((0, ui_components_1.shouldRenderInkPromptCursor)({
        input: "测试",
        disabled: false,
        imeSafe: true,
    }), false);
});
(0, node_test_1.default)("keeps the Ink prompt cursor for normal prompts", () => {
    strict_1.default.equal((0, ui_components_1.shouldRenderInkPromptCursor)({
        input: "test",
        disabled: false,
        imeSafe: false,
    }), true);
});
