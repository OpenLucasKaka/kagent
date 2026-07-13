import assert from "node:assert/strict";
import test from "node:test";

import {
  selectTranscriptViewport,
  type TranscriptEntry,
} from "./transcript";

function entry(
  id: string,
  role: TranscriptEntry["role"],
  text: string,
): TranscriptEntry {
  return {
    id,
    role,
    status: "complete",
    text,
  };
}

test("does not start the live viewport with an orphaned older assistant answer", () => {
  const entries = [
    entry("u1", "user", "first prompt"),
    entry("a1", "assistant", "previous answer\nline 2\nline 3\nline 4"),
    entry("u2", "user", "next prompt"),
    entry("a2", "assistant", "next answer"),
  ];

  const visible = selectTranscriptViewport(entries, {
    columns: 80,
    rows: 10,
    reservedRows: 1,
  });

  assert.deepEqual(
    visible.map((item) => item.id),
    ["u2", "a2"],
  );
});

test("keeps a previous user with its assistant answer when both fit", () => {
  const entries = [
    entry("u1", "user", "first prompt"),
    entry("a1", "assistant", "previous answer"),
    entry("u2", "user", "next prompt"),
    entry("a2", "assistant", "next answer"),
  ];

  const visible = selectTranscriptViewport(entries, {
    columns: 80,
    rows: 12,
    reservedRows: 1,
  });

  assert.deepEqual(
    visible.map((item) => item.id),
    ["u1", "a1", "u2", "a2"],
  );
});

test("keeps the latest user prompt with an oversized assistant answer", () => {
  const entries = [
    entry("u1", "user", "那你是谁"),
    entry("a1", "assistant", Array(40).fill("我是 kagent").join("\n")),
  ];

  const visible = selectTranscriptViewport(entries, {
    columns: 80,
    rows: 10,
    reservedRows: 2,
  });

  assert.deepEqual(
    visible.map((item) => item.id),
    ["u1", "a1"],
  );
});
