import { EventEmitter } from "node:events";
import assert from "node:assert/strict";
import test from "node:test";

import {
  KagentInkApp,
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

test("uses Ctrl+O to expand active activity without changing the transcript", () => {
  const harness = createHarness();
  const runtime = idleRuntime();

  harness.render(runtime);
  harness.effects[0]();
  harness.effects[1]();
  runtime.emitReady();
  harness.render(runtime);
  harness.inputEvents.emit("input", "plan");
  harness.render(runtime);
  harness.inputEvents.emit("input", "\r");
  harness.render(runtime);

  const before = harness.states[2] as {
    activity: { expanded: boolean } | null;
    transcript: unknown;
  };
  assert.equal(before.activity?.expanded, false);
  const transcript = before.transcript;

  harness.inputEvents.emit("input", "\x0f");

  const after = harness.states[2] as {
    activity: { expanded: boolean } | null;
    transcript: unknown;
  };
  assert.equal(after.activity?.expanded, true);
  assert.equal(after.transcript, transcript);
});

test("keeps Ctrl+O bound to the latest completed result when activity is idle", () => {
  const harness = createHarness();
  const runtime = idleRuntime();

  harness.render(runtime);
  harness.effects[0]();
  harness.effects[1]();
  runtime.emitReady();
  harness.render(runtime);
  harness.inputEvents.emit("input", "plan");
  harness.render(runtime);
  harness.inputEvents.emit("input", "\r");
  runtime.emitRun({
    type: "run_progress",
    event: {
      type: "tool_completed",
      presentation: { title: "Result", detail: "Ready", content: "Details" },
    },
  });
  runtime.emitRun({ type: "run_completed", status: "done", answer: "Done", payload: {} });
  harness.render(runtime);

  harness.inputEvents.emit("input", "\x0f");
  const state = harness.states[2] as {
    activity: unknown;
    transcript: { entries: Array<{ title?: string; expanded?: boolean }> };
  };
  assert.equal(state.activity, null);
  assert.equal(state.transcript.entries.at(-2)?.title, "Result");
  assert.equal(state.transcript.entries.at(-2)?.expanded, true);
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

test("renders active runtime activity between messages and approval without a duplicate status line", () => {
  const harness = createHarness();
  const runtime = idleRuntime();

  harness.render(runtime);
  harness.effects[0]();
  harness.effects[1]();
  runtime.emitReady();
  harness.render(runtime);
  harness.inputEvents.emit("input", "plan");
  harness.render(runtime);
  harness.inputEvents.emit("input", "\r");
  runtime.emitRun({
    type: "run_progress",
    event: { type: "answer_started" },
  });
  const activeText = renderTreeText(harness.render(runtime));
  assert.match(activeText, /Writing the response/);
  assert.match(activeText, /Ctrl\+O details · Esc stop/);
  assert.doesNotMatch(activeText, /Working/);

  runtime.emitRun({
    type: "approval_required",
    action_id: "approve",
    title: "Send the report",
    target: "team@example.test",
    reason: "The user asked for this action.",
  });
  const text = renderTreeText(harness.render(runtime));

  assert.match(text, /Waiting for your decision/);
  assert.match(text, /Permission required/);
  assert.equal(text.indexOf("Waiting for your decision") < text.indexOf("Permission required"), true);
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

function idleRuntime(): {
  emitReady: () => void;
  emitRun: (event: unknown) => void;
  subscribe: (handler: (event: unknown) => void) => () => void;
  run: (_goal: string, handler: (event: unknown) => void) => void;
  command: () => void;
  steer: () => void;
  close: () => void;
  cancel: () => void;
} {
  let lifecycleHandler: ((event: unknown) => void) | undefined;
  let runHandler: ((event: unknown) => void) | undefined;
  return {
    emitReady() {
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
    },
    emitRun(event) {
      runHandler?.(event);
    },
    subscribe(handler) {
      lifecycleHandler = handler;
      return () => undefined;
    },
    run(_goal, handler) {
      runHandler = handler;
    },
    command() {},
    steer() {},
    close() {},
    cancel() {},
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
