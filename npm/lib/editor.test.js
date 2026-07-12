"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const editor_1 = require("./editor");
const terminal_text_1 = require("./terminal-text");
(0, node_test_1.default)("moves vertically across a soft-wrapped input line", () => {
    const state = {
        ...(0, editor_1.createEditorState)(),
        value: "abcdefghij",
        cursor: 8,
    };
    const movedUp = (0, editor_1.moveCursorVertical)(state, -1, 5);
    const movedDown = (0, editor_1.moveCursorVertical)(movedUp, 1, 5);
    strict_1.default.equal((0, editor_1.editorVisualLineCount)(state.value, 5), 3);
    strict_1.default.equal(movedUp.cursor, 3);
    strict_1.default.equal(movedDown.cursor, 8);
});
(0, node_test_1.default)("counts the rendered end cursor at an exact-width boundary", () => {
    strict_1.default.equal((0, editor_1.editorVisualLineCount)("abcde", 5), 2);
});
(0, node_test_1.default)("uses terminal column width for wide graphemes", () => {
    const state = {
        ...(0, editor_1.createEditorState)(),
        value: "你好世界",
        cursor: 4,
    };
    strict_1.default.equal((0, editor_1.editorVisualLineCount)(state.value, 6), 2);
    strict_1.default.equal((0, editor_1.moveCursorVertical)(state, -1, 6).cursor, 1);
});
(0, node_test_1.default)("matches terminal width for emoji presentation and supplementary CJK", () => {
    for (const grapheme of ["©️", "1️⃣", "↔️", "𠀀"]) {
        strict_1.default.equal((0, terminal_text_1.terminalGraphemeWidth)(grapheme), 2, grapheme);
        strict_1.default.equal((0, editor_1.editorVisualLineCount)(`a${grapheme}b`, 3), 2, grapheme);
    }
});
(0, node_test_1.default)("removes terminal control sequences from display text", () => {
    strict_1.default.equal((0, terminal_text_1.terminalSafeText)("safe\u001b]52;c;SGVsbG8=\u0007tail\nnext"), "safe]52;c;SGVsbG8=tailnext");
});
(0, node_test_1.default)("preserves vertical navigation across explicit newlines", () => {
    const state = {
        ...(0, editor_1.createEditorState)(),
        value: "abc\ndef",
        cursor: 6,
    };
    strict_1.default.equal((0, editor_1.moveCursorVertical)(state, -1, 10).cursor, 2);
});
(0, node_test_1.default)("reports one visual line for short input", () => {
    strict_1.default.equal((0, editor_1.editorVisualLineCount)("short", 20), 1);
});
