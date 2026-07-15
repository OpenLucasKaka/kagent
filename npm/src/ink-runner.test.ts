import assert from "node:assert/strict";
import test from "node:test";

import * as inkRunner from "./ink-runner";

type CursorControl = {
  position: string;
  restore: string;
};

type CursorSynchronizedStdout = {
  cursor: { update: (control: CursorControl | null) => void };
  stdout: NodeJS.WriteStream;
};

test("synchronizes the terminal cursor at the actual Ink stdout write boundary", () => {
  const createCursorSynchronizedStdout = (
    inkRunner as unknown as {
      createCursorSynchronizedStdout?: (
        stdout: NodeJS.WriteStream,
      ) => CursorSynchronizedStdout;
    }
  ).createCursorSynchronizedStdout;

  assert.equal(typeof createCursorSynchronizedStdout, "function");
  if (!createCursorSynchronizedStdout) {
    return;
  }

  const writes: string[] = [];
  const target = {
    write(value: string | Uint8Array) {
      writes.push(String(value));
      return true;
    },
  } as unknown as NodeJS.WriteStream;
  const synchronized = createCursorSynchronizedStdout(target);

  synchronized.cursor.update({ position: "position-1", restore: "restore-1" });
  synchronized.stdout.write("frame-1");
  assert.deepEqual(writes, ["frame-1", "position-1"]);

  synchronized.cursor.update({ position: "position-2", restore: "restore-2" });
  synchronized.stdout.write("frame-2");
  assert.deepEqual(writes, [
    "frame-1",
    "position-1",
    "restore-1",
    "frame-2",
    "position-2",
  ]);

  synchronized.cursor.update(null);
  synchronized.stdout.write("frame-3");
  assert.deepEqual(writes, [
    "frame-1",
    "position-1",
    "restore-1",
    "frame-2",
    "position-2",
    "restore-2",
    "frame-3",
  ]);
});
