import { estimateTextRows } from "./terminal-width";

export type TranscriptRole = "user" | "assistant" | "command" | "system";
export type TranscriptStatus = "complete" | "streaming" | "cancelled" | "error";

export type TranscriptEntry = {
  id: string;
  role: TranscriptRole;
  status: TranscriptStatus;
  text: string;
  title?: string;
  detail?: string;
  content?: string;
  expanded?: boolean;
};

export type TranscriptState = {
  entries: TranscriptEntry[];
  activeAssistantId: string | null;
  nextId: number;
  maxEntries: number;
};

export type TranscriptAction =
  | { type: "user_submitted"; text: string }
  | { type: "command_completed"; title: string; text: string; clear: boolean }
  | { type: "assistant_started" }
  | { type: "assistant_delta"; text: string }
  | {
      type: "assistant_completed";
      text: string;
      outcome: "complete" | "cancelled";
    }
  | {
      type: "result_completed";
      title: string;
      detail: string;
      content: string;
    }
  | { type: "toggle_latest_result" }
  | { type: "error"; text: string };

export type TranscriptViewport = {
  columns: number;
  rows: number;
  reservedRows?: number;
};

export function createTranscriptState(maxEntries = 100): TranscriptState {
  return {
    entries: [],
    activeAssistantId: null,
    nextId: 1,
    maxEntries: Math.max(1, maxEntries),
  };
}

export function transcriptReducer(
  state: TranscriptState,
  action: TranscriptAction,
): TranscriptState {
  if (action.type === "user_submitted") {
    return appendEntry(state, "user", action.text, "complete");
  }
  if (action.type === "command_completed") {
    const base = action.clear ? { ...state, entries: [], activeAssistantId: null } : state;
    return appendEntry(base, "command", action.text, "complete", action.title);
  }
  if (action.type === "assistant_started") {
    if (state.activeAssistantId) {
      return state;
    }
    const next = appendEntry(state, "assistant", "", "streaming");
    return { ...next, activeAssistantId: next.entries.at(-1)?.id || null };
  }
  if (action.type === "assistant_delta") {
    const started = state.activeAssistantId
      ? state
      : transcriptReducer(state, { type: "assistant_started" });
    return updateActiveAssistant(started, (entry) => ({
      ...entry,
      text: entry.text + action.text,
      status: "streaming",
    }));
  }
  if (action.type === "assistant_completed") {
    const status = action.outcome === "cancelled" ? "cancelled" : "complete";
    if (state.activeAssistantId) {
      const completed = updateActiveAssistant(state, (entry) => ({
        ...entry,
        text: action.text || entry.text,
        status,
      }));
      return { ...completed, activeAssistantId: null };
    }
    const last = state.entries.at(-1);
    if (last?.role === "assistant" && last.text === action.text && last.status === status) {
      return state;
    }
    return appendEntry(state, "assistant", action.text, status);
  }
  if (action.type === "result_completed") {
    const entry: TranscriptEntry = {
      id: `m-${state.nextId}`,
      role: "command",
      status: "complete",
      text: "",
      title: action.title,
      ...(action.detail ? { detail: action.detail } : {}),
      ...(action.content ? { content: action.content, expanded: false } : {}),
    };
    return retain({
      ...state,
      entries: state.entries.concat(entry),
      nextId: state.nextId + 1,
    });
  }
  if (action.type === "toggle_latest_result") {
    let index = -1;
    for (let candidate = state.entries.length - 1; candidate >= 0; candidate -= 1) {
      if (state.entries[candidate].content) {
        index = candidate;
        break;
      }
    }
    if (index < 0) {
      return state;
    }
    return {
      ...state,
      entries: state.entries.map((entry, entryIndex) =>
        entryIndex === index ? { ...entry, expanded: !entry.expanded } : entry,
      ),
    };
  }
  return appendEntry(state, "system", action.text, "error");
}

export function progressTranscriptAction(
  event: Record<string, unknown>,
): TranscriptAction | null {
  const type = String(event.type || "");
  if (type === "answer_started") {
    return { type: "assistant_started" };
  }
  if (type === "answer_delta") {
    return { type: "assistant_delta", text: String(event.delta ?? event.text ?? "") };
  }
  if (type === "answer_completed") {
    return {
      type: "assistant_completed",
      text: String(event.answer ?? event.text ?? ""),
      outcome: "complete",
    };
  }
  if (type === "tool_completed") {
    const presentation = event.presentation;
    if (!presentation || typeof presentation !== "object") {
      return null;
    }
    const payload = presentation as Record<string, unknown>;
    const title = String(payload.title || "").trim();
    if (!title) {
      return null;
    }
    const detail = String(payload.detail || "").trim();
    return {
      type: "result_completed",
      title,
      detail: payload.truncated === true
        ? [detail, "truncated"].filter(Boolean).join(" · ")
        : detail,
      content: String(payload.content || "").trim(),
    };
  }
  return null;
}

export function selectTranscriptViewport(
  entries: TranscriptEntry[],
  viewport: TranscriptViewport,
  offset = 0,
): TranscriptEntry[] {
  if (entries.length === 0) {
    return [];
  }
  const availableRows = Math.max(1, viewport.rows - (viewport.reservedRows ?? 0));
  const safeOffset = clampTranscriptOffset(entries, offset);
  const end = entries.length - safeOffset;
  let usedRows = 0;
  let start = end - 1;
  for (let index = end - 1; index >= 0; index -= 1) {
    const rows = estimateEntryRows(entries[index], viewport.columns);
    if (usedRows > 0 && usedRows + rows > availableRows) {
      break;
    }
    usedRows += rows;
    start = index;
  }
  start = avoidOrphanedLeadingAssistant(
    entries,
    start,
    end,
    usedRows,
    availableRows,
    viewport.columns,
  );
  return entries.slice(start, end);
}

export function moveTranscriptViewport(
  entries: TranscriptEntry[],
  viewport: TranscriptViewport,
  offset: number,
  direction: "older" | "newer",
): number {
  if (entries.length === 0) {
    return 0;
  }
  const safeOffset = clampTranscriptOffset(entries, offset);
  const pageOffsets = transcriptPageOffsets(entries, viewport);
  if (direction === "older") {
    return pageOffsets.find((pageOffset) => pageOffset > safeOffset)
      ?? pageOffsets.at(-1)
      ?? 0;
  }
  for (let index = pageOffsets.length - 1; index >= 0; index -= 1) {
    if (pageOffsets[index] < safeOffset) {
      return pageOffsets[index];
    }
  }
  return 0;
}

export function clampTranscriptOffset(
  entries: TranscriptEntry[],
  offset: number,
): number {
  if (entries.length === 0) {
    return 0;
  }
  return Math.min(Math.max(Math.trunc(offset), 0), entries.length - 1);
}

function transcriptPageOffsets(
  entries: TranscriptEntry[],
  viewport: TranscriptViewport,
): number[] {
  const offsets = [0];
  while (offsets.at(-1)! < entries.length - 1) {
    const current = offsets.at(-1)!;
    const visibleCount = Math.max(
      1,
      selectTranscriptViewport(entries, viewport, current).length,
    );
    const next = clampTranscriptOffset(entries, current + visibleCount);
    if (next === current) {
      break;
    }
    offsets.push(next);
  }
  return offsets;
}

function appendEntry(
  state: TranscriptState,
  role: TranscriptRole,
  text: string,
  status: TranscriptStatus,
  title?: string,
): TranscriptState {
  const entry: TranscriptEntry = {
    id: `m-${state.nextId}`,
    role,
    status,
    text,
    ...(title ? { title } : {}),
  };
  return retain({
    ...state,
    entries: state.entries.concat(entry),
    nextId: state.nextId + 1,
  });
}

function updateActiveAssistant(
  state: TranscriptState,
  update: (entry: TranscriptEntry) => TranscriptEntry,
): TranscriptState {
  if (!state.activeAssistantId) {
    return state;
  }
  return {
    ...state,
    entries: state.entries.map((entry) =>
      entry.id === state.activeAssistantId ? update(entry) : entry,
    ),
  };
}

function retain(state: TranscriptState): TranscriptState {
  if (state.entries.length <= state.maxEntries) {
    return state;
  }
  const entries = state.entries.slice(-state.maxEntries);
  const activeAssistantId = entries.some((entry) => entry.id === state.activeAssistantId)
    ? state.activeAssistantId
    : null;
  return { ...state, entries, activeAssistantId };
}

function avoidOrphanedLeadingAssistant(
  entries: TranscriptEntry[],
  start: number,
  end: number,
  usedRows: number,
  availableRows: number,
  columns: number,
): number {
  let nextStart = start;
  let nextUsedRows = usedRows;
  while (
    nextStart > 0 &&
    nextStart < end - 1 &&
    entries[nextStart].role === "assistant" &&
    entries[nextStart - 1].role === "user"
  ) {
    const userRows = estimateEntryRows(entries[nextStart - 1], columns);
    if (nextUsedRows + userRows <= availableRows) {
      return nextStart - 1;
    }
    nextUsedRows -= estimateEntryRows(entries[nextStart], columns);
    nextStart += 1;
  }
  return nextStart;
}

function estimateEntryRows(entry: TranscriptEntry, columns: number): number {
  const contentColumns = Math.max(4, columns - 4);
  const titleRows = entry.title ? estimateTextRows(entry.title, contentColumns) : 0;
  const detailRows = entry.detail ? estimateTextRows(entry.detail, contentColumns) : 0;
  const contentRows = entry.expanded && entry.content
    ? estimateTextRows(entry.content, contentColumns)
    : 0;
  return Math.max(
    1,
    titleRows + detailRows + contentRows + estimateTextRows(entry.text, contentColumns),
  ) + 1;
}
