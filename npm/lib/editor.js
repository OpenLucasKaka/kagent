"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createEditorState = createEditorState;
exports.insertInput = insertInput;
exports.deleteBeforeCursor = deleteBeforeCursor;
exports.deleteAtCursor = deleteAtCursor;
exports.moveCursor = moveCursor;
exports.moveCursorToStart = moveCursorToStart;
exports.moveCursorToEnd = moveCursorToEnd;
exports.submitInput = submitInput;
exports.navigateHistory = navigateHistory;
exports.splitGraphemes = splitGraphemes;
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: "grapheme" });
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
    const characters = splitGraphemes(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    const before = characters.slice(0, cursor).join("");
    const inserted = splitGraphemes(rawInput).filter(isPrintableGrapheme).join("");
    const after = characters.slice(cursor).join("");
    const prefix = before + inserted;
    return editBuffer(state, prefix + after, splitGraphemes(prefix).length);
}
function deleteBeforeCursor(state) {
    const characters = splitGraphemes(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    if (cursor === 0) {
        return state;
    }
    characters.splice(cursor - 1, 1);
    return editBuffer(state, characters.join(""), cursor - 1);
}
function deleteAtCursor(state) {
    const characters = splitGraphemes(state.value);
    const cursor = clampCursor(state.cursor, characters.length);
    if (cursor === characters.length) {
        return state;
    }
    characters.splice(cursor, 1);
    return editBuffer(state, characters.join(""), cursor);
}
function moveCursor(state, offset) {
    const length = splitGraphemes(state.value).length;
    return {
        ...state,
        cursor: clampCursor(state.cursor + offset, length),
    };
}
function moveCursorToStart(state) {
    return { ...state, cursor: 0 };
}
function moveCursorToEnd(state) {
    return { ...state, cursor: splitGraphemes(state.value).length };
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
        cursor: splitGraphemes(state.draft).length,
        historyIndex: null,
        draft: "",
    };
}
function splitGraphemes(value) {
    return Array.from(GRAPHEME_SEGMENTER.segment(value), ({ segment }) => segment);
}
function historyState(state, historyIndex, draft) {
    const value = state.history[historyIndex];
    return {
        ...state,
        value,
        cursor: splitGraphemes(value).length,
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
function isPrintableGrapheme(character) {
    if (character === "\n") {
        return true;
    }
    const codePoint = character.codePointAt(0) || 0;
    return codePoint >= 32 && codePoint !== 127;
}
