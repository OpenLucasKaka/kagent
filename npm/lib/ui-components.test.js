"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const ui_components_1 = require("./ui-components");
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
