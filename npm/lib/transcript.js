"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTranscriptState = createTranscriptState;
exports.transcriptReducer = transcriptReducer;
exports.progressTranscriptAction = progressTranscriptAction;
exports.selectTranscriptViewport = selectTranscriptViewport;
exports.moveTranscriptViewport = moveTranscriptViewport;
exports.clampTranscriptOffset = clampTranscriptOffset;
const terminal_width_1 = require("./terminal-width");
function createTranscriptState(maxEntries = 100) {
    return {
        entries: [],
        activeAssistantId: null,
        nextId: 1,
        maxEntries: Math.max(1, maxEntries),
    };
}
function transcriptReducer(state, action) {
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
    return appendEntry(state, "system", action.text, "error");
}
function progressTranscriptAction(event) {
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
    return null;
}
function selectTranscriptViewport(entries, viewport, offset = 0) {
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
    return entries.slice(start, end);
}
function moveTranscriptViewport(entries, viewport, offset, direction) {
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
function clampTranscriptOffset(entries, offset) {
    if (entries.length === 0) {
        return 0;
    }
    return Math.min(Math.max(Math.trunc(offset), 0), entries.length - 1);
}
function transcriptPageOffsets(entries, viewport) {
    const offsets = [0];
    while (offsets.at(-1) < entries.length - 1) {
        const current = offsets.at(-1);
        const visibleCount = Math.max(1, selectTranscriptViewport(entries, viewport, current).length);
        const next = clampTranscriptOffset(entries, current + visibleCount);
        if (next === current) {
            break;
        }
        offsets.push(next);
    }
    return offsets;
}
function appendEntry(state, role, text, status, title) {
    const entry = {
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
function updateActiveAssistant(state, update) {
    if (!state.activeAssistantId) {
        return state;
    }
    return {
        ...state,
        entries: state.entries.map((entry) => entry.id === state.activeAssistantId ? update(entry) : entry),
    };
}
function retain(state) {
    if (state.entries.length <= state.maxEntries) {
        return state;
    }
    const entries = state.entries.slice(-state.maxEntries);
    const activeAssistantId = entries.some((entry) => entry.id === state.activeAssistantId)
        ? state.activeAssistantId
        : null;
    return { ...state, entries, activeAssistantId };
}
function estimateEntryRows(entry, columns) {
    const contentColumns = Math.max(4, columns - 4);
    const titleRows = entry.title ? (0, terminal_width_1.estimateTextRows)(entry.title, contentColumns) : 0;
    return Math.max(1, titleRows + (0, terminal_width_1.estimateTextRows)(entry.text, contentColumns)) + 1;
}
