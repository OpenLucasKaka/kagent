"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_events_1 = require("node:events");
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const App_1 = require("./App");
(0, node_test_1.default)("does not submit the same prompt twice before React renders the busy state", () => {
    const harness = createHarness();
    let lifecycleHandler;
    const submitted = [];
    const runtime = {
        subscribe(handler) {
            lifecycleHandler = handler;
            return () => undefined;
        },
        run(goal) {
            submitted.push(goal);
        },
        command() { },
        steer() { },
        close() { },
        cancel() { },
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
    strict_1.default.deepEqual(submitted, ["那你是谁"]);
    const runtimeState = harness.states[2];
    strict_1.default.deepEqual(runtimeState.transcript.entries.map((entry) => [
        entry.role,
        entry.text,
    ]), [["user", "那你是谁"]]);
});
(0, node_test_1.default)("hides only the empty interactive prompt while the runtime is busy", () => {
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("idle"), true);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("approval"), true);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("error"), true);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("thinking"), false);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("thinking", "steer"), true);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("cancelling"), false);
    strict_1.default.equal((0, App_1.shouldRenderInteractivePrompt)("starting"), false);
});
(0, node_test_1.default)("does not render the session header during the startup frame", () => {
    strict_1.default.equal((0, App_1.shouldRenderSessionHeader)("starting", 0), false);
    strict_1.default.equal((0, App_1.shouldRenderSessionHeader)("idle", 0), true);
    strict_1.default.equal((0, App_1.shouldRenderSessionHeader)("thinking", 0), true);
    strict_1.default.equal((0, App_1.shouldRenderSessionHeader)("idle", 1), false);
});
(0, node_test_1.default)("omits the session header from the startup render tree", () => {
    const harness = createHarness();
    const tree = harness.render({
        subscribe() {
            return () => undefined;
        },
        close() { },
        cancel() { },
    });
    const text = renderTreeText(tree);
    strict_1.default.doesNotMatch(text, /◆ kagent/);
    strict_1.default.match(text, /Starting runtime/);
});
(0, node_test_1.default)("defers terminal cursor positioning until after the Ink render flush", () => {
    const writes = [];
    const scheduled = [];
    const cleanup = (0, App_1.scheduleTerminalCursorSync)({ position: "position", restore: "restore" }, {
        write(value) {
            writes.push(value);
        },
        defer(callback) {
            scheduled.push(callback);
            return callback;
        },
        cancel(token) {
            const index = scheduled.indexOf(token);
            if (index >= 0) {
                scheduled.splice(index, 1);
            }
        },
    });
    strict_1.default.deepEqual(writes, []);
    scheduled.shift()?.();
    strict_1.default.deepEqual(writes, ["position"]);
    cleanup();
    strict_1.default.deepEqual(writes, ["position", "restore"]);
});
(0, node_test_1.default)("does not restore terminal cursor when deferred positioning was cancelled", () => {
    const writes = [];
    const scheduled = [];
    const cleanup = (0, App_1.scheduleTerminalCursorSync)({ position: "position", restore: "restore" }, {
        write(value) {
            writes.push(value);
        },
        defer(callback) {
            scheduled.push(callback);
            return callback;
        },
        cancel(token) {
            const index = scheduled.indexOf(token);
            if (index >= 0) {
                scheduled.splice(index, 1);
            }
        },
    });
    cleanup();
    strict_1.default.deepEqual(writes, []);
    strict_1.default.equal(scheduled.length, 0);
});
function createHarness() {
    const states = [];
    const refs = [];
    const inputEvents = new node_events_1.EventEmitter();
    let effects = [];
    let stateCursor = 0;
    let refCursor = 0;
    const React = {
        createElement(type, props, ...children) {
            if (typeof type === "function") {
                return type({
                    ...(props && typeof props === "object" ? props : {}),
                    children,
                });
            }
            return { type, props, children };
        },
        useEffect(effect) {
            effects.push(effect);
        },
        useLayoutEffect(effect) {
            effects.push(effect);
        },
        useRef(value) {
            const index = refCursor;
            refCursor += 1;
            if (!refs[index]) {
                refs[index] = { current: value };
            }
            return refs[index];
        },
        useState(initial) {
            const index = stateCursor;
            stateCursor += 1;
            if (!(index in states)) {
                states[index] = typeof initial === "function"
                    ? initial()
                    : initial;
            }
            return [
                states[index],
                (update) => {
                    states[index] = typeof update === "function"
                        ? update(states[index])
                        : update;
                },
            ];
        },
    };
    const Ink = {
        Box: "Box",
        Text: "Text",
        useApp() {
            return { exit() { } };
        },
        useStdin() {
            return { internal_eventEmitter: inputEvents, setRawMode() { } };
        },
    };
    return {
        get effects() {
            return effects;
        },
        inputEvents,
        render(runtime) {
            stateCursor = 0;
            refCursor = 0;
            effects = [];
            return (0, App_1.KagentInkApp)({
                React: React,
                Ink: Ink,
                runtimeSessionFactory: () => runtime,
            });
        },
        states,
    };
}
function renderTreeText(value) {
    if (typeof value === "string" || typeof value === "number") {
        return String(value);
    }
    if (!value || typeof value !== "object") {
        return "";
    }
    if (Array.isArray(value)) {
        return value.map(renderTreeText).join("");
    }
    const node = value;
    return renderTreeText(node.children || []);
}
