import { EventEmitter } from "node:events";
import assert from "node:assert/strict";
import test from "node:test";

import {
  KagentInkApp,
  scheduleTerminalCursorSync,
  shouldRenderInteractivePrompt,
} from "./App";
import type ReactNamespace from "react";

test("does not submit the same prompt twice before React renders the busy state", () => {
  const harness = createHarness();
  let lifecycleHandler: ((event: unknown) => void) | undefined;
  const submitted: string[] = [];
  const runtime = {
    subscribe(handler: (event: unknown) => void) {
      lifecycleHandler = handler;
      return () => undefined;
    },
    run(goal: string) {
      submitted.push(goal);
    },
    command() {},
    steer() {},
    close() {},
    cancel() {},
  };

  harness.render(runtime);
  harness.effects[0]();
  harness.effects[1]();
  lifecycleHandler?.({
    type: "runtime_ready",
    provider: {
      configured: true,
      provider: "test",
      display_name: "Test",
      base_url_configured: true,
      model: "model",
      api_key_configured: true,
    },
    provider_options: [],
    session_commands: [],
  });
  harness.render(runtime);
  harness.inputEvents.emit("input", "那你是谁");
  harness.render(runtime);

  harness.inputEvents.emit("input", "\r");
  harness.inputEvents.emit("input", "\r");

  assert.deepEqual(submitted, ["那你是谁"]);
  const runtimeState = harness.states[2] as {
    transcript: { entries: Array<{ role: string; text: string }> };
  };
  assert.deepEqual(
    runtimeState.transcript.entries.map((entry) => [
      entry.role,
      entry.text,
    ]),
    [["user", "那你是谁"]],
  );
});

test("hides only the empty interactive prompt while the runtime is busy", () => {
  assert.equal(shouldRenderInteractivePrompt("idle"), true);
  assert.equal(shouldRenderInteractivePrompt("approval"), true);
  assert.equal(shouldRenderInteractivePrompt("error"), true);
  assert.equal(shouldRenderInteractivePrompt("thinking"), false);
  assert.equal(shouldRenderInteractivePrompt("thinking", "steer"), true);
  assert.equal(shouldRenderInteractivePrompt("cancelling"), false);
  assert.equal(shouldRenderInteractivePrompt("starting"), false);
});

test("defers terminal cursor positioning until after the Ink render flush", () => {
  const writes: string[] = [];
  const scheduled: Array<() => void> = [];
  const cleanup = scheduleTerminalCursorSync(
    { position: "position", restore: "restore" },
    {
      write(value: string) {
        writes.push(value);
      },
      defer(callback: () => void) {
        scheduled.push(callback);
        return callback;
      },
      cancel(token: () => void) {
        const index = scheduled.indexOf(token);
        if (index >= 0) {
          scheduled.splice(index, 1);
        }
      },
    },
  );

  assert.deepEqual(writes, []);
  scheduled.shift()?.();
  assert.deepEqual(writes, ["position"]);
  cleanup();
  assert.deepEqual(writes, ["position", "restore"]);
});

function createHarness(): {
  effects: Array<() => (() => void) | undefined>;
  inputEvents: EventEmitter;
  render: (runtime: unknown) => unknown;
  states: unknown[];
} {
  const states: unknown[] = [];
  const refs: Array<{ current: unknown }> = [];
  const inputEvents = new EventEmitter();
  let effects: Array<() => (() => void) | undefined> = [];
  let stateCursor = 0;
  let refCursor = 0;

  const React = {
    createElement(type: unknown, props: unknown, ...children: unknown[]) {
      return { type, props, children };
    },
    useEffect(effect: () => (() => void) | undefined) {
      effects.push(effect);
    },
    useLayoutEffect(effect: () => (() => void) | undefined) {
      effects.push(effect);
    },
    useRef(value: unknown) {
      const index = refCursor;
      refCursor += 1;
      if (!refs[index]) {
        refs[index] = { current: value };
      }
      return refs[index];
    },
    useState(initial: unknown) {
      const index = stateCursor;
      stateCursor += 1;
      if (!(index in states)) {
        states[index] = typeof initial === "function"
          ? (initial as () => unknown)()
          : initial;
      }
      return [
        states[index],
        (update: unknown) => {
          states[index] = typeof update === "function"
            ? (update as (current: unknown) => unknown)(states[index])
            : update;
        },
      ];
    },
  };
  const Ink = {
    Box: "Box",
    Text: "Text",
    useApp() {
      return { exit() {} };
    },
    useStdin() {
      return { internal_eventEmitter: inputEvents, setRawMode() {} };
    },
  };

  return {
    get effects() {
      return effects;
    },
    inputEvents,
    render(runtime: unknown) {
      stateCursor = 0;
      refCursor = 0;
      effects = [];
      return KagentInkApp({
        React: React as unknown as typeof ReactNamespace,
        Ink: Ink as never,
        runtimeSessionFactory: () => runtime as never,
      });
    },
    states,
  };
}
