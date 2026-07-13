import { EventEmitter } from "node:events";
import assert from "node:assert/strict";
import test from "node:test";

import {
  KagentInkApp,
  scheduleTerminalCursorSync,
  shouldRenderInteractivePrompt,
  shouldRenderSessionHeader,
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

test("does not render the session header during the startup frame", () => {
  assert.equal(shouldRenderSessionHeader("starting", 0), false);
  assert.equal(shouldRenderSessionHeader("idle", 0), true);
  assert.equal(shouldRenderSessionHeader("thinking", 0), true);
  assert.equal(shouldRenderSessionHeader("idle", 1), false);
});

test("omits the session header from the startup render tree", () => {
  const harness = createHarness();
  const tree = harness.render({
    subscribe() {
      return () => undefined;
    },
    close() {},
    cancel() {},
  });
  const text = renderTreeText(tree);

  assert.doesNotMatch(text, /◆ kagent/);
  assert.match(text, /Starting runtime/);
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
      if (typeof type === "function") {
        return (type as (componentProps: unknown) => unknown)({
          ...(props && typeof props === "object" ? props : {}),
          children,
        });
      }
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

function renderTreeText(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (!value || typeof value !== "object") {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map(renderTreeText).join("");
  }
  const node = value as { children?: unknown[] };
  return renderTreeText(node.children || []);
}
