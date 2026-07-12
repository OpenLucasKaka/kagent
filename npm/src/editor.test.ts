import assert from "node:assert/strict";
import test from "node:test";

import {
  createEditorState,
  editorVisualLineCount,
  moveCursorVertical,
} from "./editor";
import { terminalGraphemeWidth, terminalSafeText } from "./terminal-text";

test("moves vertically across a soft-wrapped input line", () => {
  const state = {
    ...createEditorState(),
    value: "abcdefghij",
    cursor: 8,
  };

  const movedUp = moveCursorVertical(state, -1, 5);
  const movedDown = moveCursorVertical(movedUp, 1, 5);

  assert.equal(editorVisualLineCount(state.value, 5), 3);
  assert.equal(movedUp.cursor, 3);
  assert.equal(movedDown.cursor, 8);
});

test("counts the rendered end cursor at an exact-width boundary", () => {
  assert.equal(editorVisualLineCount("abcde", 5), 2);
});

test("uses terminal column width for wide graphemes", () => {
  const state = {
    ...createEditorState(),
    value: "你好世界",
    cursor: 4,
  };

  assert.equal(editorVisualLineCount(state.value, 6), 2);
  assert.equal(moveCursorVertical(state, -1, 6).cursor, 1);
});

test("matches terminal width for emoji presentation and supplementary CJK", () => {
  for (const grapheme of ["©️", "1️⃣", "↔️", "𠀀"]) {
    assert.equal(terminalGraphemeWidth(grapheme), 2, grapheme);
    assert.equal(editorVisualLineCount(`a${grapheme}b`, 3), 2, grapheme);
  }
});

test("removes terminal control sequences from display text", () => {
  assert.equal(
    terminalSafeText("safe\u001b]52;c;SGVsbG8=\u0007tail\nnext"),
    "safe]52;c;SGVsbG8=tailnext",
  );
});

test("preserves vertical navigation across explicit newlines", () => {
  const state = {
    ...createEditorState(),
    value: "abc\ndef",
    cursor: 6,
  };

  assert.equal(moveCursorVertical(state, -1, 10).cursor, 2);
});

test("reports one visual line for short input", () => {
  assert.equal(editorVisualLineCount("short", 20), 1);
});
