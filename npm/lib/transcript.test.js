"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const transcript_1 = require("./transcript");
function entry(id, role, text) {
    return {
        id,
        role,
        status: "complete",
        text,
    };
}
(0, node_test_1.default)("does not start the live viewport with an orphaned older assistant answer", () => {
    const entries = [
        entry("u1", "user", "first prompt"),
        entry("a1", "assistant", "previous answer\nline 2\nline 3\nline 4"),
        entry("u2", "user", "next prompt"),
        entry("a2", "assistant", "next answer"),
    ];
    const visible = (0, transcript_1.selectTranscriptViewport)(entries, {
        columns: 80,
        rows: 10,
        reservedRows: 1,
    });
    strict_1.default.deepEqual(visible.map((item) => item.id), ["u2", "a2"]);
});
(0, node_test_1.default)("keeps a previous user with its assistant answer when both fit", () => {
    const entries = [
        entry("u1", "user", "first prompt"),
        entry("a1", "assistant", "previous answer"),
        entry("u2", "user", "next prompt"),
        entry("a2", "assistant", "next answer"),
    ];
    const visible = (0, transcript_1.selectTranscriptViewport)(entries, {
        columns: 80,
        rows: 12,
        reservedRows: 1,
    });
    strict_1.default.deepEqual(visible.map((item) => item.id), ["u1", "a1", "u2", "a2"]);
});
(0, node_test_1.default)("keeps the latest user prompt with an oversized assistant answer", () => {
    const entries = [
        entry("u1", "user", "那你是谁"),
        entry("a1", "assistant", Array(40).fill("我是 kagent").join("\n")),
    ];
    const visible = (0, transcript_1.selectTranscriptViewport)(entries, {
        columns: 80,
        rows: 10,
        reservedRows: 2,
    });
    strict_1.default.deepEqual(visible.map((item) => item.id), ["u1", "a1"]);
});
