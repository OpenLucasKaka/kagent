import { splitGraphemes, terminalGraphemeWidth } from "./terminal-text";

export { splitGraphemes } from "./terminal-text";

export type EditorBuffer = {
  value: string;
  cursor: number;
};

export type EditorState = EditorBuffer & {
  history: string[];
  historyIndex: number | null;
  draft: string;
};

export type Submission = {
  value: string | null;
  state: EditorState;
};

export function createEditorState(history: string[] = []): EditorState {
  return {
    value: "",
    cursor: 0,
    history: history.slice(),
    historyIndex: null,
    draft: "",
  };
}

export function insertInput<T extends EditorBuffer>(state: T, rawInput: string): T {
  const characters = splitGraphemes(state.value);
  const cursor = clampCursor(state.cursor, characters.length);
  const before = characters.slice(0, cursor).join("");
  const inserted = splitGraphemes(rawInput).filter(isPrintableGrapheme).join("");
  const after = characters.slice(cursor).join("");
  const prefix = before + inserted;

  return editBuffer(state, prefix + after, splitGraphemes(prefix).length);
}

export function deleteBeforeCursor<T extends EditorBuffer>(state: T): T {
  const characters = splitGraphemes(state.value);
  const cursor = clampCursor(state.cursor, characters.length);
  if (cursor === 0) {
    return state;
  }
  characters.splice(cursor - 1, 1);
  return editBuffer(state, characters.join(""), cursor - 1);
}

export function deleteAtCursor<T extends EditorBuffer>(state: T): T {
  const characters = splitGraphemes(state.value);
  const cursor = clampCursor(state.cursor, characters.length);
  if (cursor === characters.length) {
    return state;
  }
  characters.splice(cursor, 1);
  return editBuffer(state, characters.join(""), cursor);
}

export function moveCursor<T extends EditorBuffer>(state: T, offset: number): T {
  const length = splitGraphemes(state.value).length;
  return {
    ...state,
    cursor: clampCursor(state.cursor + offset, length),
  };
}

export function moveCursorVertical<T extends EditorBuffer>(
  state: T,
  direction: -1 | 1,
  columns = Number.MAX_SAFE_INTEGER,
): T {
  const characters = splitGraphemes(state.value);
  const cursor = clampCursor(state.cursor, characters.length);
  const positions = visualCursorPositions(characters, columns);
  const current = positions[cursor];
  const targetRow = current.row + direction;
  if (targetRow < 0 || targetRow >= positions.at(-1)!.row + 1) {
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

export function editorVisualLineCount(value: string, columns: number): number {
  const positions = visualCursorPositions(splitGraphemes(value), columns);
  const finalPosition = positions.at(-1)!;
  return finalPosition.row + 1;
}

export function moveCursorToStart<T extends EditorBuffer>(state: T): T {
  return { ...state, cursor: 0 };
}

export function moveCursorToEnd<T extends EditorBuffer>(state: T): T {
  return { ...state, cursor: splitGraphemes(state.value).length };
}

export function submitInput(state: EditorState): Submission {
  const value = state.value.trim();
  if (!value) {
    return { value: null, state };
  }
  return {
    value,
    state: createEditorState(state.history.concat(value)),
  };
}

export function navigateHistory(state: EditorState, offset: number): EditorState {
  if (state.history.length === 0 || offset === 0) {
    return state;
  }
  if (offset < 0) {
    const historyIndex =
      state.historyIndex === null
        ? state.history.length - 1
        : Math.max(state.historyIndex - 1, 0);
    return historyState(
      state,
      historyIndex,
      state.historyIndex === null ? state.value : state.draft,
    );
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

function historyState(
  state: EditorState,
  historyIndex: number,
  draft: string,
): EditorState {
  const value = state.history[historyIndex];
  return {
    ...state,
    value,
    cursor: splitGraphemes(value).length,
    historyIndex,
    draft,
  };
}

function editBuffer<T extends EditorBuffer>(state: T, value: string, cursor: number): T {
  return {
    ...state,
    value,
    cursor,
    ...(isEditorState(state) ? { historyIndex: null, draft: "" } : {}),
  };
}

function isEditorState(state: EditorBuffer): state is EditorState {
  return "history" in state;
}

function clampCursor(cursor: number, length: number): number {
  return Math.min(Math.max(cursor, 0), length);
}

function visualCursorPositions(
  characters: string[],
  columns: number,
): Array<{ row: number; column: number }> {
  const safeColumns = Math.max(1, Math.trunc(columns));
  const positions = [{ row: 0, column: 0 }];
  let row = 0;
  let column = 0;
  characters.forEach((character) => {
    if (character === "\n") {
      row += 1;
      column = 0;
    } else {
      const width = terminalGraphemeWidth(character);
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

function isPrintableGrapheme(character: string): boolean {
  if (character === "\n") {
    return true;
  }
  const codePoint = character.codePointAt(0) || 0;
  return codePoint >= 32 && codePoint !== 127;
}
