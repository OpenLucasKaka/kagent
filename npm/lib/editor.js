"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.splitGraphemes = void 0;
exports.createEditorState = createEditorState;
exports.insertInput = insertInput;
exports.deleteBeforeCursor = deleteBeforeCursor;
exports.deleteAtCursor = deleteAtCursor;
exports.moveCursor = moveCursor;
exports.moveCursorVertical = moveCursorVertical;
exports.editorVisualLineCount = editorVisualLineCount;
exports.moveCursorToStart = moveCursorToStart;
exports.moveCursorToEnd = moveCursorToEnd;
exports.submitInput = submitInput;
exports.navigateHistory = navigateHistory;
const terminal_text_1 = require("./terminal-text");
var terminal_text_2 = require("./terminal-text");
Object.defineProperty(exports, "splitGraphemes", { enumerable: true, get: function () { return terminal_text_2.splitGraphemes; } });
function createEditorState(history = []) {
    return {
        value: "",
        cursor: 0,
        history: history.slice(),
        historyIndex: null,
        draft: "",
    };
}
function insertInput(state, rawInput) {
    const characters = (0, terminal_text_1.splitGraphemes)(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    const before = characters.slice(0, cursor).join("");
    const inserted = (0, terminal_text_1.splitGraphemes)(rawInput).filter(isPrintableGrapheme).join("");
    const after = characters.slice(cursor).join("");
    const prefix = before + inserted;
    return editBuffer(state, prefix + after, (0, terminal_text_1.splitGraphemes)(prefix).length);
}
function deleteBeforeCursor(state) {
    const characters = (0, terminal_text_1.splitGraphemes)(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    if (cursor === 0) {
        return state;
    }
    characters.splice(cursor - 1, 1);
    return editBuffer(state, characters.join(""), cursor - 1);
}
function deleteAtCursor(state) {
    const characters = (0, terminal_text_1.splitGraphemes)(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    if (cursor === characters.length) {
        return state;
    }
    characters.splice(cursor, 1);
    return editBuffer(state, characters.join(""), cursor);
}
function moveCursor(state, offset) {
    const length = (0, terminal_text_1.splitGraphemes)(state.value).length;
    return {
        ...state,
        cursor: clampCursor(state.cursor + offset, length),
    };
}
function moveCursorVertical(state, direction, columns = Number.MAX_SAFE_INTEGER) {
    const characters = (0, terminal_text_1.splitGraphemes)(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    const positions = visualCursorPositions(characters, columns);
    const current = positions[cursor];
    const targetRow = current.row + direction;
    if (targetRow < 0 || targetRow >= positions.at(-1).row + 1) {
        return state;
    }
    let targetCursor = cursor;
    let targetDistance = Number.MAX_SAFE_INTEGER;
    positions.forEach((position, index) => {
        if (position.row !== targetRow) {
            return;
        }
        const distance = Math.abs(position.column - current.column);
        if (distance < targetDistance) {
            targetCursor = index;
            targetDistance = distance;
        }
    });
    return {
        ...state,
        cursor: targetCursor,
    };
}
function editorVisualLineCount(value, columns) {
    const positions = visualCursorPositions((0, terminal_text_1.splitGraphemes)(value), columns);
    const finalPosition = positions.at(-1);
    return finalPosition.row + 1;
}
function moveCursorToStart(state) {
    return { ...state, cursor: 0 };
}
function moveCursorToEnd(state) {
    return { ...state, cursor: (0, terminal_text_1.splitGraphemes)(state.value).length };
}
function submitInput(state) {
    const value = state.value.trim();
    if (!value) {
        return { value: null, state };
    }
    return {
        value,
        state: createEditorState(state.history.concat(value)),
    };
}
function navigateHistory(state, offset) {
    if (state.history.length === 0 || offset === 0) {
        return state;
    }
    if (offset < 0) {
        const historyIndex = state.historyIndex === null
            ? state.history.length - 1
            : Math.max(state.historyIndex - 1, 0);
        return historyState(state, historyIndex, state.historyIndex === null ? state.value : state.draft);
    }
    if (state.historyIndex === null) {
        return state;
    }
    if (state.historyIndex < state.history.length - 1) {
        return historyState(state, state.historyIndex + 1, state.draft);
    }
    return {
        ...state,
        value: state.draft,
        cursor: (0, terminal_text_1.splitGraphemes)(state.draft).length,
        historyIndex: null,
        draft: "",
    };
}
function historyState(state, historyIndex, draft) {
    const value = state.history[historyIndex];
    return {
        ...state,
        value,
        cursor: (0, terminal_text_1.splitGraphemes)(value).length,
        historyIndex,
        draft,
    };
}
function editBuffer(state, value, cursor) {
    return {
        ...state,
        value,
        cursor,
        ...(isEditorState(state) ? { historyIndex: null, draft: "" } : {}),
    };
}
function isEditorState(state) {
    return "history" in state;
}
function clampCursor(cursor, length) {
    return Math.min(Math.max(cursor, 0), length);
}
function visualCursorPositions(characters, columns) {
    const safeColumns = Math.max(1, Math.trunc(columns));
    const positions = [{ row: 0, column: 0 }];
    let row = 0;
    let column = 0;
    characters.forEach((character) => {
        if (character === "\n") {
            row += 1;
            column = 0;
        }
        else {
            const width = (0, terminal_text_1.terminalGraphemeWidth)(character);
            if (column > 0 && column + width > safeColumns) {
                row += 1;
                column = 0;
            }
            column += width;
            if (column >= safeColumns) {
                row += 1;
                column = 0;
            }
        }
        positions.push({ row, column });
    });
    return positions;
}
function isPrintableGrapheme(character) {
    if (character === "\n") {
        return true;
    }
    const codePoint = character.codePointAt(0) || 0;
    return codePoint >= 32 && codePoint !== 127;
}
