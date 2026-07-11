import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_npm_package_declares_daily_use_bins():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert package_json["name"] == "@openlucaskaka/kagent"
    assert package_json["bin"] == {
        "kagent": "npm/bin/kagent.js",
        "kagent-serve": "npm/bin/kagent-serve.js",
    }


def test_npm_and_python_package_versions_match():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")

    assert f'version = "{package_json["version"]}"' in pyproject


def test_npm_package_ships_python_runtime_sources():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert "pyproject.toml" in package_json["files"]
    assert "src" in package_json["files"]
    assert "npm" in package_json["files"]


def test_npm_package_declares_ink_tui_dependencies():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert package_json["dependencies"]["ink"].startswith("^5.")
    assert package_json["dependencies"]["react"].startswith("^18.")


def test_npm_package_declares_typed_ink_build_pipeline():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    tsconfig = json.loads(Path("tsconfig.json").read_text(encoding="utf-8"))

    assert package_json["scripts"]["build:cli"] == "tsc -p tsconfig.json"
    assert "npm run build:cli" in package_json["scripts"]["check"]
    assert package_json["devDependencies"]["typescript"].startswith("^5.")
    assert package_json["devDependencies"]["@types/react"].startswith("^18.")
    assert tsconfig["compilerOptions"]["jsx"] == "react-jsx"
    assert tsconfig["include"] == ["npm/src/**/*.ts", "npm/src/**/*.tsx"]


def test_npm_ink_source_uses_jsonl_runtime_protocol():
    source_paths = [
        Path("npm/src/App.tsx"),
        Path("npm/src/protocol.ts"),
        Path("npm/src/runtime-client.ts"),
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in source_paths)

    assert "run_request" in combined
    assert "runtime_ready" in combined
    assert "runtime_unavailable" in combined
    assert "run_progress" in combined
    assert "steer_request" in combined
    assert "run_steer_queued" in combined
    assert "run_steer_rejected" in combined
    assert "approval_required" in combined
    assert "approval_response" in combined
    assert "provider_configure" in combined
    assert "provider_configured" in combined
    assert "provider_configuration_failed" in combined
    assert "session_command" in combined
    assert "session_command_completed" in combined
    assert "session_command_failed" in combined
    assert "run_completed" in combined
    assert "kagent.cli.stdio_runtime" in combined
    assert "--classic" not in Path("npm/src/runtime-client.ts").read_text(encoding="utf-8")


def test_npm_terminal_layout_adapts_to_narrow_and_wide_terminals():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {createTerminalLayout} = require("./npm/lib/ui-components");
const {estimateTextRows} = require("./npm/lib/terminal-width");

assert.deepEqual(createTerminalLayout(40, 24, {approval: true, commandMenu: true}), {
  columns: 40,
  rows: 24,
  compact: true,
  horizontalPadding: 0,
  commandLimit: 4,
  reservedRows: 17,
});
assert.deepEqual(createTerminalLayout(100, 30, {approval: false, commandMenu: true}), {
  columns: 100,
  rows: 30,
  compact: false,
  horizontalPadding: 1,
  commandLimit: 6,
  reservedRows: 13,
});
assert.equal(
  createTerminalLayout(40, 24, {
    approval: true,
    commandMenu: true,
    prompt: "第一行\n第二行",
  }).reservedRows,
  18,
);
assert.equal(estimateTextRows("中文abcd", 6), 2);
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_npm_ui_components_render_with_real_ink_at_narrow_and_wide_widths():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const React = require("react");
const {PassThrough} = require("node:stream");
const ui = require("./npm/lib/ui-components");

async function renderAt(columns) {
  const Ink = await import("ink");
  const output = [];
  const stdout = new PassThrough();
  stdout.columns = columns;
  stdout.rows = 24;
  stdout.isTTY = true;
  stdout.on("data", (chunk) => output.push(chunk));
  const stdin = new PassThrough();
  stdin.isTTY = true;
  stdin.setRawMode = () => {};
  const stderr = new PassThrough();
  const layout = ui.createTerminalLayout(columns, 24, {approval: true, commandMenu: true});
  const menu = {
    query: "/",
    selectedIndex: 0,
    selectedCommand: "/status",
    options: [
      {
        command: "/status",
        description: "Show provider, workspace, and session status",
        aliases: [],
      },
      {command: "/memory", description: "Inspect recent conversation memory", aliases: []},
      {command: "/tools", description: "List available capabilities", aliases: []},
      {command: "/clear", description: "Clear visible conversation", aliases: []},
      {command: "/reset", description: "Reset session state", aliases: []},
    ],
  };
  const multilinePrompt = "帮我继续完善这个非常长的终端输入内容并且不要卡住\n保留第二行";
  const element = React.createElement(
    Ink.Box,
    {flexDirection: "column", width: columns},
    React.createElement(ui.Header, {
      React,
      Box: Ink.Box,
      Text: Ink.Text,
      compact: layout.compact,
      provider: {
        configured: true,
        provider: "qwen",
        display_name: "Qwen",
        base_url_configured: true,
        model: "qwen3.5-122b-a10b",
        api_key_configured: true,
      },
      setup: false,
    }),
    React.createElement(ui.MessageList, {
      React,
      Box: Ink.Box,
      Text: Ink.Text,
      messages: [
        {
          id: "m-1",
          role: "assistant",
          status: "streaming",
          text: "正在整理一份很长的周末旅行计划，内容会自动换行并保持输入区域稳定。",
        },
        {
          id: "m-2",
          role: "command",
          status: "complete",
          text: "",
          title: "Updated files docs/plan.md",
          detail: "update docs/plan.md · 128 bytes",
          content: "- old line\n+ new line",
          expanded: true,
        },
      ],
    }),
    React.createElement(ui.TranscriptPosition, {
      React,
      Text: Ink.Text,
      newerCount: 3,
    }),
    React.createElement(ui.ApprovalPanel, {
      React,
      Box: Ink.Box,
      Text: Ink.Text,
      approval: {
        type: "approval_required",
        action_id: "open",
        title: "Open a website",
        target: "https://github.com/OpenLucasKaka/Kagent/issues/very-long-target",
        reason: "The user requested this external action.",
      },
      compact: layout.compact,
      showDetails: true,
    }),
    React.createElement(ui.CommandPalette, {
      React,
      Box: Ink.Box,
      Text: Ink.Text,
      compact: layout.compact,
      limit: layout.commandLimit,
      menu,
    }),
    React.createElement(ui.PromptLine, {
      React,
      Box: Ink.Box,
      Text: Ink.Text,
      cursor: Array.from(multilinePrompt.split("\n")[0]).length,
      disabled: false,
      input: multilinePrompt,
    }),
  );
  const instance = Ink.render(element, {
    stdout,
    stdin,
    stderr,
    debug: true,
    exitOnCtrlC: false,
  });
  await new Promise((resolve) => setTimeout(resolve, 50));
  instance.unmount();
  await new Promise((resolve) => setTimeout(resolve, 10));
  return output.map((chunk) => chunk.toString("utf8"));
}

async function main() {
  const {default: stripAnsi} = await import("strip-ansi");
  const {default: stringWidth} = await import("string-width");
  for (const columns of [40, 100]) {
    const chunks = await renderAt(columns);
    const frameChunks = chunks.filter((chunk) => chunk.includes("kagent"));
    assert.ok(frameChunks.length > 0, JSON.stringify(chunks));
    const plain = stripAnsi(frameChunks.at(-1));
    assert.match(plain, /kagent/);
    assert.match(plain, /History · 3 newer/);
    assert.match(plain, /Permission required/);
    assert.match(plain, /Ask kagent|帮我继续完善/);
    assert.match(plain, /保留第二行/);
    assert.match(plain, /Updated files docs\/plan.md/);
    assert.match(plain, /\+ new line/);
    assert.doesNotMatch(plain, /apply_patch|workspace_diff/);
    const overflow = plain
      .split("\n")
      .map((line) => ({line, width: stringWidth(line)}))
      .filter(({width}) => width > columns);
    assert.deepEqual(overflow, []);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_npm_ink_runtime_keeps_one_session_and_hides_internal_tool_names():
    app = Path("npm/src/App.tsx").read_text(encoding="utf-8")
    ui = Path("npm/src/ui-components.tsx").read_text(encoding="utf-8")
    client = Path("npm/src/runtime-client.ts").read_text(encoding="utf-8")

    assert "createRuntimeSessionClient" in app
    assert "respondToApproval" in app
    assert "runtime.command" in app
    assert "Permission required" in ui
    assert "approval.title" in ui
    assert "approval.target" in ui
    assert "approval.tool" not in ui
    assert "child.stdin.end" not in client
    assert "approval_response" in client
    assert "runtime session is busy" in client


def test_npm_ink_editor_model_handles_graphemes_navigation_deletion_and_history():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {
  createEditorState,
  deleteBeforeCursor,
  deleteAtCursor,
  insertInput,
  moveCursor,
  moveCursorToEnd,
  moveCursorToStart,
  navigateHistory,
  splitGraphemes,
  submitInput,
} = require("./npm/lib/editor");
const {isSessionCommandInput} = require("./npm/lib/App");

assert.deepEqual(splitGraphemes("你👍🏽e\u0301"), ["你", "👍🏽", "e\u0301"]);

let composed = insertInput(createEditorState(), "👍");
composed = insertInput(composed, "🏽");
assert.deepEqual([composed.value, composed.cursor], ["👍🏽", 1]);
composed = moveCursor(composed, -1);
composed = deleteAtCursor(composed);
assert.deepEqual([composed.value, composed.cursor], ["", 0]);

let combining = insertInput(createEditorState(), "e");
combining = insertInput(combining, "\u0301");
assert.deepEqual([combining.value, combining.cursor], ["e\u0301", 1]);

let state = insertInput(createEditorState(), "你👍🏽e\u0301");
assert.equal(state.value, "你👍🏽e\u0301");
assert.equal(state.cursor, 3);

state = moveCursor(state, -1);
assert.equal(state.cursor, 2);
state = moveCursor(state, 1);
assert.equal(state.cursor, 3);

state = moveCursorToStart(state);
assert.equal(state.cursor, 0);
state = moveCursorToEnd(state);
assert.equal(state.cursor, 3);

state = deleteBeforeCursor(state);
assert.equal(state.value, "你👍🏽");
assert.equal(state.cursor, 2);

state = moveCursorToStart(state);
state = deleteAtCursor(state);
assert.equal(state.value, "👍🏽");
assert.equal(state.cursor, 0);

state = insertInput(state, "A");
assert.equal(state.value, "A👍🏽");
assert.equal(state.cursor, 1);

let multiline = insertInput(createEditorState(), "第一行\n第二行");
assert.deepEqual([multiline.value, multiline.cursor], ["第一行\n第二行", 7]);
multiline = moveCursor(multiline, -3);
multiline = deleteBeforeCursor(multiline);
assert.equal(multiline.value, "第一行第二行");
assert.equal(submitInput(insertInput(createEditorState(), "a\nb")).value, "a\nb");

let submitted = submitInput(insertInput(createEditorState(), "first"));
assert.equal(submitted.value, "first");
state = submitted.state;

submitted = submitInput(insertInput(state, "second"));
assert.equal(submitted.value, "second");
state = insertInput(submitted.state, "draft");

state = navigateHistory(state, -1);
assert.equal(state.value, "second");
assert.equal(state.cursor, 6);
state = navigateHistory(state, -1);
assert.equal(state.value, "first");
state = navigateHistory(state, -1);
assert.equal(state.value, "first");

state = navigateHistory(state, 1);
assert.equal(state.value, "second");
state = navigateHistory(state, 1);
assert.equal(state.value, "draft");
assert.equal(state.cursor, 5);
state = navigateHistory(state, 1);
assert.equal(state.value, "draft");

assert.equal(submitInput(createEditorState()).value, null);

assert.equal(isSessionCommandInput("/status"), true);
assert.equal(isSessionCommandInput("  /memory"), true);
assert.equal(isSessionCommandInput("/status\nexplain"), false);
assert.equal(isSessionCommandInput("tell me /status"), false);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_terminal_input_bridge_preserves_raw_editing_keys():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {createTerminalInputBridge} = require("./npm/lib/terminal-input");

const events = [];
const bridge = createTerminalInputBridge((input, key) => {
  events.push([input, key.name, key.ctrl]);
});

for (const sequence of [
  "\x7f",
  "\x1b[3~",
  "\x1b[H",
  "\x1b[F",
  "\x1b[D",
  "\x1b[C",
  "\x1b[A",
  "\x1b[B",
  "\x1b[5~",
  "\x1b[6~",
  "\x01",
  "\x05",
  "\x03",
  "你",
]) {
  bridge.write(sequence);
}
bridge.write("z\x1b[D\x7f\r");
bridge.write("first\nsecond");
bridge.write("\x1b[20");
bridge.write("0~third\r\n");
bridge.write("fourth\n👍\x1b[20");
bridge.write("1~");
bridge.close();

assert.deepEqual(events, [
  ["", "backspace", false],
  ["", "delete", false],
  ["", "home", false],
  ["", "end", false],
  ["", "left", false],
  ["", "right", false],
  ["", "up", false],
  ["", "down", false],
  ["", "pageup", false],
  ["", "pagedown", false],
  ["a", "a", true],
  ["e", "e", true],
  ["c", "c", true],
  ["你", undefined, false],
  ["z", "z", false],
  ["", "left", false],
  ["", "backspace", false],
  ["", "return", false],
  ["first\nsecond", undefined, false],
  ["third\nfourth\n👍", undefined, false],
]);

const modifiedReturns = [];
const modifiedBridge = createTerminalInputBridge((input, key) => {
  modifiedReturns.push([
    input,
    key.name,
    key.ctrl,
    key.meta,
    key.shift,
    key.sequence,
  ]);
});
modifiedBridge.write("\x1b[13;2u");
modifiedBridge.write("\x1b\r");
modifiedBridge.write("\n");
modifiedBridge.close();
assert.deepEqual(modifiedReturns, [
  ["", "return", false, false, true, "\x1b[13;2u"],
  ["", "return", false, true, false, "\x1b\r"],
  ["", "enter", false, false, false, "\n"],
]);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_ink_app_uses_raw_terminal_input_and_cooperative_ctrl_c():
    node = shutil.which("node")
    if node is None:
        return

    app = Path("npm/src/App.tsx").read_text(encoding="utf-8")
    runner = Path("npm/src/ink-runner.tsx").read_text(encoding="utf-8")

    assert "Ink.useStdin()" in app
    assert "createTerminalInputBridge" in app
    assert "Ink.useInput" not in app
    assert 'key.name === "backspace"' in app
    assert 'key.name === "delete"' in app
    assert 'key.name === "home"' in app
    assert 'key.name === "end"' in app
    assert 'key.name === "pageup"' in app
    assert 'key.name === "pagedown"' in app
    assert 'key.shift || key.meta || key.sequence === "\\n"' in app
    assert "runtime.steer" in app
    assert 'status === "thinking" && key.name === "escape"' in app
    assert 'key.ctrl && key.name === "o"' in app
    assert "[React, transcript.nextId]" in app
    assert "showError(errorMessage(error));\n      showError(errorMessage(error));" not in app
    assert "exitOnCtrlC: false" in runner

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {KagentInkApp} = require("./npm/lib/App");

const states = [];
const effects = [];
const rawModes = [];
let exits = 0;
const React = {
  createElement(type, props, ...children) {
    return {type, props, children};
  },
  useEffect(effect) {
    effects.push(effect);
  },
  useRef(value) {
    return {current: value};
  },
  useState(initial) {
    const index = states.length;
    states.push(typeof initial === "function" ? initial() : initial);
    return [states[index], (update) => {
      states[index] = typeof update === "function" ? update(states[index]) : update;
    }];
  },
};
const inputEvents = new EventEmitter();
const Ink = {
  Box: "Box",
  Text: "Text",
  useApp() {
    return {exit() { exits += 1; }};
  },
  useStdin() {
    return {
      internal_eventEmitter: inputEvents,
      setRawMode(value) { rawModes.push(value); },
    };
  },
};
const runtime = {
  subscribe() { return () => {}; },
  close() {},
  cancel() {},
};

KagentInkApp({React, Ink, runtimeSessionFactory: () => runtime});
const cleanup = effects[0]();
const editor = () => states[1];
assert.equal(inputEvents.listenerCount("input"), 1);

inputEvents.emit("input", "abc\x1b[D\x7f");
assert.deepEqual([editor().value, editor().cursor], ["ac", 1]);
inputEvents.emit("input", "\x1b[3~");
assert.deepEqual([editor().value, editor().cursor], ["a", 1]);
inputEvents.emit("input", "\x1b[H你\x1b[F!\x01X\x05Y\x1b[D\x1b[C");
assert.deepEqual([editor().value, editor().cursor], ["X你a!Y", 5]);
inputEvents.emit("input", "👍");
inputEvents.emit("input", "🏽");
assert.deepEqual([editor().value, editor().cursor], ["X你a!Y👍🏽", 6]);
inputEvents.emit("input", "\x1b[D\x1b[3~");
assert.deepEqual([editor().value, editor().cursor], ["X你a!Y", 5]);
inputEvents.emit("input", "first\nsecond");
assert.deepEqual([editor().value, editor().cursor], ["X你a!Yfirst\nsecond", 17]);
inputEvents.emit("input", "\x1b[13;2u");
assert.deepEqual([editor().value, editor().cursor], ["X你a!Yfirst\nsecond\n", 18]);
inputEvents.emit("input", "\x03");
assert.equal(exits, 1);

cleanup();
assert.deepEqual(rawModes, [true, false]);
assert.equal(inputEvents.listenerCount("input"), 0);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_ink_app_preserves_composed_graphemes_in_provider_setup():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {KagentInkApp} = require("./npm/lib/App");

const states = [];
const refs = [];
let effects = [];
let stateCursor = 0;
let refCursor = 0;
let lifecycleHandler;
let providerHandler;
let configuredProvider;

const React = {
  createElement(type, props, ...children) {
    return {type, props, children};
  },
  useEffect(effect) {
    effects.push(effect);
  },
  useRef(value) {
    const index = refCursor++;
    if (!refs[index]) refs[index] = {current: value};
    return refs[index];
  },
  useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) {
      states[index] = typeof initial === "function" ? initial() : initial;
    }
    return [states[index], (update) => {
      states[index] = typeof update === "function" ? update(states[index]) : update;
    }];
  },
};

const inputEvents = new EventEmitter();
const Ink = {
  Box: "Box",
  Text: "Text",
  useApp() {
    return {exit() {}};
  },
  useStdin() {
    return {
      internal_eventEmitter: inputEvents,
      setRawMode() {},
    };
  },
};
const runtime = {
  subscribe(handler) {
    lifecycleHandler = handler;
    return () => {};
  },
  close() {},
  cancel() {},
  configureProvider(config, handler) {
    configuredProvider = config;
    providerHandler = handler;
  },
};

function render() {
  stateCursor = 0;
  refCursor = 0;
  effects = [];
  KagentInkApp({React, Ink, runtimeSessionFactory: () => runtime});
}

render();
const inputCleanup = effects[0]();
const runtimeCleanup = effects[1]();
lifecycleHandler({
  type: "runtime_ready",
  provider: {
    configured: false,
    provider: "test",
    display_name: "Test",
    base_url_configured: false,
    model: "model",
    api_key_configured: false,
  },
  provider_options: [{
    provider: "test",
    label: "Test",
    base_url: "x",
    model: "model",
    api_key_required: false,
  }],
});
render();

inputEvents.emit("input", "\r");
render();
inputEvents.emit("input", "👍");
inputEvents.emit("input", "🏽");
assert.deepEqual(
  [states[2].setup.editor.value, states[2].setup.editor.cursor],
  ["x👍🏽", 2],
);
inputEvents.emit("input", "e");
inputEvents.emit("input", "\u0301");
assert.deepEqual(
  [states[2].setup.editor.value, states[2].setup.editor.cursor],
  ["x👍🏽e\u0301", 3],
);
inputEvents.emit("input", "a\nb");
assert.deepEqual(
  [states[2].setup.editor.value, states[2].setup.editor.cursor],
  ["x👍🏽e\u0301a b", 6],
);
inputEvents.emit("input", "\r");
render();
inputEvents.emit("input", "\r");
render();
inputEvents.emit("input", "\r");
render();
effects[4]();
assert.deepEqual(configuredProvider, {
  provider: "test",
  baseUrl: "x👍🏽e\u0301a b",
  model: "model",
  apiKey: "",
});
providerHandler({
  type: "provider_configured",
  provider: {
    configured: true,
    provider: "test",
    display_name: "Test",
    base_url_configured: true,
    model: "model",
    api_key_configured: false,
  },
});
assert.equal(states[2].setup, null);

inputCleanup();
runtimeCleanup();
assert.equal(inputEvents.listenerCount("input"), 0);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_provider_setup_state_machine_supports_menu_defaults_and_secret_masking():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {
  createProviderSetupState,
  maskSecret,
  providerConfiguration,
  providerSetupReducer,
} = require("./npm/lib/provider-setup");

const options = [
  {
    provider: "qwen_openai_compatible",
    label: "Qwen / DashScope",
    base_url: "https://dashscope.example/v1",
    model: "qwen-plus",
    api_key_required: true,
  },
  {
    provider: "ollama_openai_compatible",
    label: "Ollama local",
    base_url: "http://localhost:11434/v1",
    model: "llama3",
    api_key_required: false,
  },
];

let state = createProviderSetupState(options);
state = providerSetupReducer(state, {type: "select", offset: -1});
assert.equal(state.selectedIndex, 1);
state = providerSetupReducer(state, {type: "next"});
assert.equal(state.stage, "base_url");
assert.equal(state.editor.value, "http://localhost:11434/v1");
state = providerSetupReducer(state, {type: "next"});
assert.equal(state.stage, "model");
state = providerSetupReducer(state, {type: "next"});
assert.equal(state.stage, "api_key");
state = providerSetupReducer(state, {type: "next"});
assert.equal(state.stage, "saving");
assert.deepEqual(providerConfiguration(state), {
  provider: "ollama_openai_compatible",
  baseUrl: "http://localhost:11434/v1",
  model: "llama3",
  apiKey: "",
});

let required = createProviderSetupState(options);
required = providerSetupReducer(required, {type: "next"});
required = providerSetupReducer(required, {type: "next"});
required = providerSetupReducer(required, {type: "next"});
required = providerSetupReducer(required, {type: "next"});
assert.equal(required.stage, "api_key");
assert.match(required.error, /required/);
assert.equal(maskSecret("s你👍🏽"), "•••");
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_command_palette_filters_navigates_stably_and_completes():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {
  commandCompletion,
  moveCommandSelection,
  updateCommandMenu,
} = require("./npm/lib/commands");

const catalog = [
  {command: "/status", description: "show shell state", aliases: ["/stat"]},
  {command: "/config", description: "show provider config", aliases: ["/provider"]},
  {command: "/cd PATH", description: "change working directory", aliases: ["/cd"]},
  {command: "/clear", description: "clear remembered turns", aliases: ["/clear-memory"]},
];

let menu = updateCommandMenu(catalog, "/", null);
assert.deepEqual(menu.options.map((item) => item.command), [
  "/status", "/config", "/cd PATH", "/clear",
]);
assert.equal(menu.selectedCommand, "/status");

menu = moveCommandSelection(menu, 1);
assert.equal(menu.selectedCommand, "/config");
menu = updateCommandMenu(catalog, "/c", menu);
assert.deepEqual(menu.options.map((item) => item.command), [
  "/config", "/cd PATH", "/clear",
]);
assert.equal(menu.selectedCommand, "/config");

menu = moveCommandSelection(menu, -1);
assert.equal(menu.selectedCommand, "/clear");
assert.equal(commandCompletion(menu), "/clear");

const aliasMenu = updateCommandMenu(catalog, "/sta", null);
assert.equal(aliasMenu.selectedCommand, "/status");
assert.equal(commandCompletion(aliasMenu), "/status");

const argumentMenu = updateCommandMenu(catalog, "/cd", null);
assert.equal(commandCompletion(argumentMenu), "/cd ");
assert.equal(updateCommandMenu(catalog, "/cd /tmp", argumentMenu), null);
assert.equal(updateCommandMenu(catalog, "hello", null), null);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_ink_app_routes_command_menu_keys_before_prompt_history():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {KagentInkApp} = require("./npm/lib/App");

const states = [];
const refs = [];
let effects = [];
let stateCursor = 0;
let refCursor = 0;
let lifecycleHandler;
let commandValue = "";

const React = {
  createElement(type, props, ...children) { return {type, props, children}; },
  useEffect(effect) { effects.push(effect); },
  useRef(value) {
    const index = refCursor++;
    if (!refs[index]) refs[index] = {current: value};
    return refs[index];
  },
  useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (update) => {
      states[index] = typeof update === "function" ? update(states[index]) : update;
    }];
  },
};
const inputEvents = new EventEmitter();
const Ink = {
  Box: "Box",
  Text: "Text",
  useApp() { return {exit() {}}; },
  useStdin() {
    return {internal_eventEmitter: inputEvents, setRawMode() {}};
  },
};
const runtime = {
  subscribe(handler) { lifecycleHandler = handler; return () => {}; },
  command(value) { commandValue = value; },
  close() {},
  cancel() {},
};

function render() {
  stateCursor = 0;
  refCursor = 0;
  effects = [];
  return KagentInkApp({React, Ink, runtimeSessionFactory: () => runtime});
}

render();
const inputCleanup = effects[0]();
const runtimeCleanup = effects[1]();
lifecycleHandler({
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
  session_commands: [
    {command: "/status", description: "show status", aliases: ["/stat"]},
    {command: "/config", description: "show config", aliases: ["/provider"]},
    {command: "/cd PATH", description: "change directory", aliases: ["/cd"]},
  ],
});
render();

inputEvents.emit("input", "/");
render();
inputEvents.emit("input", "\x1b[B");
render();
assert.equal(states[6], "/config");
inputEvents.emit("input", "\t");
render();
assert.deepEqual([states[1].value, states[1].cursor], ["/config", 7]);
inputEvents.emit("input", "\r");
assert.equal(commandValue, "/config");

inputCleanup();
runtimeCleanup();
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_transcript_reducer_streams_without_duplicates_and_bounds_viewport():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {
  createTranscriptState,
  moveTranscriptViewport,
  progressTranscriptAction,
  selectTranscriptViewport,
  transcriptReducer,
} = require("./npm/lib/transcript");

let state = createTranscriptState(4);
state = transcriptReducer(state, {type: "user_submitted", text: "制定计划"});
state = transcriptReducer(state, {type: "assistant_started"});
const assistantId = state.activeAssistantId;
state = transcriptReducer(state, {type: "assistant_delta", text: "第一"});
state = transcriptReducer(state, {type: "assistant_delta", text: "步"});
assert.equal(state.entries.at(-1).id, assistantId);
assert.equal(state.entries.at(-1).text, "第一步");
assert.equal(state.entries.at(-1).status, "streaming");

state = transcriptReducer(state, {
  type: "assistant_completed",
  text: "第一步",
  outcome: "complete",
});
state = transcriptReducer(state, {
  type: "assistant_completed",
  text: "第一步",
  outcome: "complete",
});
assert.equal(state.entries.filter((entry) => entry.role === "assistant").length, 1);
assert.equal(state.entries.at(-1).status, "complete");

let cancelled = createTranscriptState();
cancelled = transcriptReducer(cancelled, {type: "assistant_started"});
cancelled = transcriptReducer(cancelled, {
  type: "assistant_completed",
  text: "已停止。",
  outcome: "cancelled",
});
assert.equal(cancelled.entries[0].status, "cancelled");

assert.deepEqual(progressTranscriptAction({type: "answer_started"}), {
  type: "assistant_started",
});
assert.deepEqual(progressTranscriptAction({type: "answer_delta", delta: "你好"}), {
  type: "assistant_delta",
  text: "你好",
});

for (const text of ["二", "三", "四", "五"]) {
  state = transcriptReducer(state, {type: "user_submitted", text});
}
assert.equal(state.entries.length, 4);
assert.deepEqual(state.entries.map((entry) => entry.text), ["二", "三", "四", "五"]);

const viewport = selectTranscriptViewport(state.entries, {
  columns: 10,
  rows: 5,
  reservedRows: 2,
});
assert.equal(viewport.at(-1).text, "五");
assert.ok(viewport.length >= 1);

const latestViewport = selectTranscriptViewport(state.entries, {
  columns: 10,
  rows: 4,
  reservedRows: 2,
});
assert.deepEqual(latestViewport.map((entry) => entry.text), ["五"]);
const olderOffset = moveTranscriptViewport(
  state.entries,
  {columns: 10, rows: 4, reservedRows: 2},
  0,
  "older",
);
assert.equal(olderOffset, 1);
assert.deepEqual(
  selectTranscriptViewport(
    state.entries,
    {columns: 10, rows: 4, reservedRows: 2},
    olderOffset,
  ).map((entry) => entry.text),
  ["四"],
);
assert.equal(
  moveTranscriptViewport(
    state.entries,
    {columns: 10, rows: 4, reservedRows: 2},
    olderOffset,
    "newer",
  ),
  0,
);
assert.equal(
  moveTranscriptViewport(
    state.entries,
    {columns: 10, rows: 4, reservedRows: 2},
    999,
    "older",
  ),
  state.entries.length - 1,
);
assert.equal(
  moveTranscriptViewport([], {columns: 10, rows: 4, reservedRows: 2}, 3, "older"),
  0,
);

const unevenEntries = [
  {
    id: "u-1",
    role: "assistant",
    status: "complete",
    text: "很长很长很长很长很长",
    title: undefined,
  },
  {id: "u-2", role: "user", status: "complete", text: "中", title: undefined},
  {id: "u-3", role: "assistant", status: "complete", text: "新", title: undefined},
];
const unevenViewport = {columns: 10, rows: 6, reservedRows: 2};
const unevenOlderOffset = moveTranscriptViewport(
  unevenEntries,
  unevenViewport,
  0,
  "older",
);
assert.equal(unevenOlderOffset, 2);
assert.equal(
  moveTranscriptViewport(
    unevenEntries,
    unevenViewport,
    unevenOlderOffset,
    "newer",
  ),
  0,
);

let bounded = createTranscriptState(2);
for (const text of ["一", "二", "三"]) {
  bounded = transcriptReducer(bounded, {type: "user_submitted", text});
}
assert.equal(bounded.entries.length, 2);
assert.equal(bounded.nextId, 4);

const unicodeState = [
  {id: "m-1", role: "assistant", status: "complete", text: "深圳周末旅行攻略", title: "攻略"},
  {id: "m-2", role: "user", status: "complete", text: "继续", title: undefined},
];
const unicodeViewport = selectTranscriptViewport(unicodeState, {
  columns: 8,
  rows: 3,
  reservedRows: 1,
});
assert.equal(unicodeViewport.at(-1).id, "m-2");

const resultAction = progressTranscriptAction({
  type: "tool_completed",
  presentation: {
    title: "Created Rollout plan",
    detail: "plan · markdown · 42 bytes",
    content: "# Rollout\nShip carefully",
  },
});
assert.deepEqual(resultAction, {
  type: "result_completed",
  title: "Created Rollout plan",
  detail: "plan · markdown · 42 bytes",
  content: "# Rollout\nShip carefully",
});
let resultState = transcriptReducer(createTranscriptState(), resultAction);
assert.equal(resultState.entries[0].expanded, false);
resultState = transcriptReducer(resultState, {type: "toggle_latest_result"});
assert.equal(resultState.entries[0].expanded, true);
resultState = transcriptReducer(resultState, {type: "toggle_latest_result"});
assert.equal(resultState.entries[0].expanded, false);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_app_runtime_reducer_covers_lifecycle_provider_command_and_run_events():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {appRuntimeReducer, createAppRuntimeState} = require("./npm/lib/app-state");

const provider = {
  configured: false,
  provider: "test",
  display_name: "Test",
  base_url_configured: false,
  model: "model",
  api_key_configured: false,
};
const option = {
  provider: "test",
  label: "Test",
  base_url: "https://example.test/v1",
  model: "model",
  api_key_required: false,
};
let state = createAppRuntimeState();
assert.equal(state.status, "starting");

state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "lifecycle",
  event: {
    type: "runtime_ready",
    provider,
    provider_options: [option],
    session_commands: [{command: "/status", description: "status", aliases: []}],
  },
});
assert.equal(state.status, "idle");
assert.equal(state.setup.stage, "provider");
assert.equal(state.commandCatalog[0].command, "/status");

state = appRuntimeReducer(state, {
  type: "setup_action",
  action: {type: "next"},
});
assert.equal(state.setup.stage, "base_url");
state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "provider",
  event: {
    type: "provider_configuration_failed",
    error_code: "invalid_model",
    message: "Model unavailable",
    field: "model",
  },
});
assert.equal(state.setup.stage, "model");
assert.equal(state.setup.error, "Model unavailable");

state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "provider",
  event: {type: "provider_configured", provider: {...provider, configured: true}},
});
assert.equal(state.setup, null);
assert.equal(state.provider.configured, true);

state = appRuntimeReducer(state, {type: "submit", text: "go", command: false});
state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {type: "run_steer_queued", revision: "1", replaced: "false"},
});
assert.equal(state.statusText, "Instruction queued");
state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {type: "run_progress", event: {type: "answer_started"}},
});
state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {type: "run_progress", event: {type: "answer_delta", delta: "完成"}},
});
assert.equal(state.transcript.entries.at(-1).status, "streaming");

state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {
    type: "approval_required",
    action_id: "open",
    title: "Open page",
    reason: "requested",
    target: "https://example.test",
  },
});
assert.equal(state.status, "approval");
state = appRuntimeReducer(state, {type: "approval_response", approved: true});
assert.equal(state.approval, null);
assert.equal(state.statusText, "Continuing");

state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {type: "run_completed", status: "done", answer: "完成", payload: {}},
});
assert.equal(state.status, "idle");
assert.equal(state.transcript.entries.at(-1).text, "完成");
assert.equal(state.transcript.entries.at(-1).status, "complete");

state = appRuntimeReducer(state, {type: "submit", text: "/status", command: true});
state = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "command",
  event: {
    type: "session_command_completed",
    command: "/status",
    title: "Status",
    message: "Ready",
    data: {},
    clear_messages: false,
  },
});
assert.equal(state.status, "idle");
assert.equal(state.transcript.entries.at(-1).title, "Status");

const failed = appRuntimeReducer(state, {
  type: "runtime_event",
  channel: "run",
  event: {type: "client_failed", message: "runtime stopped"},
});
assert.equal(failed.status, "error");
assert.equal(failed.approval, null);
assert.equal(failed.transcript.entries.at(-1).text, "runtime stopped");

const invalidReady = appRuntimeReducer(createAppRuntimeState(), {
  type: "runtime_event",
  channel: "lifecycle",
  event: {
    type: "runtime_ready",
    provider,
    provider_options: [],
    session_commands: [],
  },
});
assert.equal(invalidReady.status, "error");
assert.match(invalidReady.transcript.entries[0].text, /model providers/);
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_ink_app_reduces_streamed_answer_into_one_transcript_entry():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {KagentInkApp} = require("./npm/lib/App");

const states = [];
const refs = [];
let effects = [];
let stateCursor = 0;
let refCursor = 0;
let lifecycleHandler;
let runHandler;
let steered = "";

const React = {
  createElement(type, props, ...children) { return {type, props, children}; },
  useEffect(effect) { effects.push(effect); },
  useRef(value) {
    const index = refCursor++;
    if (!refs[index]) refs[index] = {current: value};
    return refs[index];
  },
  useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (update) => {
      states[index] = typeof update === "function" ? update(states[index]) : update;
    }];
  },
};
const inputEvents = new EventEmitter();
const Ink = {
  Box: "Box",
  Text: "Text",
  useApp() { return {exit() {}}; },
  useStdin() { return {internal_eventEmitter: inputEvents, setRawMode() {}}; },
};
const runtime = {
  subscribe(handler) { lifecycleHandler = handler; return () => {}; },
  run(goal, handler) {
    assert.equal(goal, "go");
    runHandler = handler;
  },
  steer(instruction) { steered = instruction; },
  close() {},
  cancel() {},
};

function render() {
  stateCursor = 0;
  refCursor = 0;
  effects = [];
  return KagentInkApp({React, Ink, runtimeSessionFactory: () => runtime});
}

render();
const inputCleanup = effects[0]();
const runtimeCleanup = effects[1]();
lifecycleHandler({
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
render();
inputEvents.emit("input", "go");
render();
inputEvents.emit("input", "\r");
render();
inputEvents.emit("input", "focus on the latest request");
render();
inputEvents.emit("input", "\r");
assert.equal(steered, "focus on the latest request");
assert.equal(states[1].value, "");

runHandler({
  type: "run_progress",
  event: {
    type: "tool_completed",
    presentation: {title: "Created Trip plan", detail: "plan · markdown"},
  },
});
runHandler({type: "run_progress", event: {type: "answer_started"}});
runHandler({type: "run_progress", event: {type: "answer_delta", delta: "你"}});
runHandler({type: "run_progress", event: {type: "answer_delta", delta: "好"}});
const streamingId = states[2].transcript.activeAssistantId;
runHandler({
  type: "run_completed",
  status: "done",
  answer: "你好",
  payload: {},
});

assert.equal(states[2].transcript.activeAssistantId, null);
assert.deepEqual(states[2].transcript.entries.map((entry) => [entry.role, entry.text]), [
  ["user", "go"],
  ["command", ""],
  ["assistant", "你好"],
]);
assert.equal(states[2].transcript.entries[1].title, "Created Trip plan");
assert.equal(states[2].transcript.entries[2].id, streamingId);

inputCleanup();
runtimeCleanup();
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_ink_app_keeps_synchronous_approval_failure_in_error_state():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {KagentInkApp} = require("./npm/lib/App");

const states = [];
const refs = [];
let effects = [];
let stateCursor = 0;
let refCursor = 0;
let lifecycleHandler;
let runHandler;
const React = {
  createElement(type, props, ...children) { return {type, props, children}; },
  useEffect(effect) { effects.push(effect); },
  useRef(value) {
    const index = refCursor++;
    if (!refs[index]) refs[index] = {current: value};
    return refs[index];
  },
  useState(initial) {
    const index = stateCursor++;
    if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
    return [states[index], (update) => {
      states[index] = typeof update === "function" ? update(states[index]) : update;
    }];
  },
};
const inputEvents = new EventEmitter();
const Ink = {
  Box: "Box",
  Text: "Text",
  useApp() { return {exit() {}}; },
  useStdin() { return {internal_eventEmitter: inputEvents, setRawMode() {}}; },
};
const runtime = {
  subscribe(handler) { lifecycleHandler = handler; return () => {}; },
  run(goal, handler) { runHandler = handler; },
  respondToApproval() {
    runHandler({type: "client_failed", message: "runtime stopped"});
  },
  close() {},
  cancel() {},
};
function render() {
  stateCursor = 0;
  refCursor = 0;
  effects = [];
  KagentInkApp({React, Ink, runtimeSessionFactory: () => runtime});
}

render();
const inputCleanup = effects[0]();
const runtimeCleanup = effects[1]();
lifecycleHandler({
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
render();
inputEvents.emit("input", "go");
render();
inputEvents.emit("input", "\r");
runHandler({
  type: "approval_required",
  action_id: "open",
  title: "Open page",
  reason: "requested",
  target: "https://example.test",
});
render();
inputEvents.emit("input", "y");
assert.equal(states[2].status, "error");
assert.equal(states[2].approval, null);
assert.equal(states[2].transcript.entries.at(-1).text, "runtime stopped");

inputCleanup();
runtimeCleanup();
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_runtime_client_reuses_python_session_and_handles_approval(tmp_path):
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const childProcess = require("node:child_process");

const runnerPath = require.resolve("./npm/lib/python-runner");
require.cache[runnerPath] = {
  id: runnerPath,
  filename: runnerPath,
  loaded: true,
  exports: {
    spawnPythonModule(moduleName, args = []) {
      return childProcess.spawn(
        process.env.KAGENT_TEST_PYTHON,
        ["-m", moduleName, ...args],
        {
          cwd: process.cwd(),
          env: process.env,
          stdio: ["pipe", "pipe", "pipe"],
        },
      );
    },
  },
};

const {createRuntimeSessionClient} = require("./npm/lib/runtime-client");
const client = createRuntimeSessionClient();

function run(goal, plan) {
  return new Promise((resolve, reject) => {
    const events = [];
    client.run(goal, (event) => {
      events.push(event);
      if (event.type === "client_failed" || event.type === "run_failed") {
        reject(new Error(event.message));
      }
      if (event.type === "run_completed") {
        resolve(events);
      }
    }, {runtimePlan: JSON.stringify(plan)});
  });
}

function command(value) {
  return new Promise((resolve, reject) => {
    const events = [];
    client.command(value, (event) => {
      events.push(event);
      if (event.type === "client_failed") {
        reject(new Error(event.message));
      }
      if (event.type === "session_command_completed" || event.type === "session_command_failed") {
        resolve(events);
      }
    });
  });
}

async function main() {
  const ready = await new Promise((resolve, reject) => {
    client.subscribe((event) => {
      if (event.type === "runtime_ready") {
        resolve(event);
      }
      if (event.type === "runtime_unavailable" || event.type === "client_failed") {
        reject(new Error(event.message));
      }
    });
  });
  assert.equal(ready.provider.configured, false);
  assert.equal(ready.provider_options.length, 4);

  const configured = await new Promise((resolve, reject) => {
    client.configureProvider({
      provider: "ollama_openai_compatible",
      baseUrl: "http://localhost:11434/v1",
      model: "llama3",
      apiKey: "",
    }, (event) => {
      if (event.type === "provider_configured") {
        resolve(event);
      }
      if (event.type === "provider_configuration_failed" || event.type === "client_failed") {
        reject(new Error(event.message));
      }
    });
  });
  assert.equal(configured.provider.display_name, "Ollama");
  assert.equal(configured.provider.api_key_configured, false);

  const status = await command("/status");
  assert.equal(status.at(-1).type, "session_command_completed");
  assert.equal(status.at(-1).title, "Session");
  assert.equal(status.at(-1).data.provider.display_name, "Ollama");

  const unknown = await command("/stats");
  assert.equal(unknown.at(-1).type, "session_command_failed");
  assert.equal(unknown.at(-1).error_code, "unknown_command");

  const first = await run("first", {actions: [], final_answer: "first answer"});
  const second = await run("second", {actions: [], final_answer: "second answer"});
  assert.equal(first.at(-1).answer, "first answer");
  assert.equal(second.at(-1).answer, "second answer");

  const approvalEvents = await new Promise((resolve, reject) => {
    const events = [];
    client.run("open github", (event) => {
      events.push(event);
      if (event.type === "approval_required") {
        assert.equal(event.title, "Open a website");
        assert.equal(event.target, "https://github.com");
        assert.equal(Object.hasOwn(event, "tool"), false);
        client.respondToApproval(event.action_id, false);
      }
      if (event.type === "client_failed" || event.type === "run_failed") {
        reject(new Error(event.message));
      }
      if (event.type === "run_completed") {
        resolve(events);
      }
    }, {
      runtimePlan: JSON.stringify({
        actions: [{
          id: "open-github",
          tool: "open_url",
          input: {url: "https://github.com"},
          reason: "requested",
        }],
      }),
    });
  });
  assert.equal(approvalEvents.at(-1).status, "cancelled");
  client.close();
}

main().catch((error) => {
  client.close();
  console.error(error);
  process.exitCode = 1;
});
"""
    env = {
        **dict(os.environ),
        "KAGENT_TEST_PYTHON": sys.executable,
        "KAGENT_LLM_CONFIG_PATH": str(tmp_path / "provider.json"),
        "KAGENT_SESSION_MEMORY_PATH": str(tmp_path / "session-memory.json"),
    }
    for name in (
        "KAGENT_LLM_PROVIDER",
        "KAGENT_LLM_BASE_URL",
        "KAGENT_LLM_API_KEY",
        "KAGENT_LLM_MODEL",
    ):
        env.pop(name, None)

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    saved = json.loads((tmp_path / "provider.json").read_text(encoding="utf-8"))
    assert saved["provider"] == "ollama_openai_compatible"


def test_npm_runtime_client_cancels_without_restarting_python_session():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {PassThrough} = require("node:stream");

let spawnCount = 0;
let killCount = 0;
let child;
const writes = [];
const runnerPath = require.resolve("./npm/lib/python-runner");
require.cache[runnerPath] = {
  id: runnerPath,
  filename: runnerPath,
  loaded: true,
  exports: {
    spawnPythonModule() {
      spawnCount += 1;
      child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.stdin = new PassThrough();
      child.stdin.on("data", (chunk) => writes.push(JSON.parse(chunk.toString("utf8"))));
      child.killed = false;
      child.exitCode = null;
      child.signalCode = null;
      child.kill = () => {
        killCount += 1;
        child.killed = true;
      };
      setImmediate(() => child.stdout.write(JSON.stringify({
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
      }) + "\n"));
      return child;
    },
  },
};

const {createRuntimeSessionClient} = require("./npm/lib/runtime-client");
const client = createRuntimeSessionClient();

async function waitFor(predicate) {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.ok(predicate(), "condition did not become true");
}

async function main() {
  await new Promise((resolve, reject) => client.subscribe((event) => {
    if (event.type === "runtime_ready") resolve();
    if (event.type === "client_failed") reject(new Error(event.message));
  }));

  const events = [];
  client.run("first", (event) => events.push(event));
  await waitFor(() => writes.length === 1);
  child.stdout.write(JSON.stringify({
    type: "run_started",
    goal: "first",
    max_iterations: "3",
  }) + "\n");

  client.steer("focus on the latest instruction");
  await waitFor(() => writes.length === 2);
  assert.deepEqual(writes[1], {
    type: "steer_request",
    instruction: "focus on the latest instruction",
  });
  child.stdout.write(JSON.stringify({
    type: "run_steer_queued",
    revision: "1",
    replaced: "false",
  }) + "\n");

  client.cancel();
  await waitFor(() => writes.length === 3);
  assert.deepEqual(writes[2], {
    type: "cancel_request",
    reason: "user requested cancellation",
  });
  assert.equal(spawnCount, 1);
  assert.equal(killCount, 0);

  child.stdout.write(JSON.stringify({
    type: "run_cancel_requested",
    reason: "user requested cancellation",
  }) + "\n");
  child.stdout.write(JSON.stringify({
    type: "run_completed",
    status: "cancelled",
    answer: "",
    payload: {},
  }) + "\n");
  await waitFor(() => events.at(-1)?.type === "run_completed");

  client.run("second", (event) => events.push(event));
  await waitFor(() => writes.length === 4);
  assert.equal(writes[3].type, "run_request");
  assert.equal(writes[3].goal, "second");
  assert.equal(spawnCount, 1);
  assert.equal(killCount, 0);
  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_npm_runtime_client_recovers_once_from_an_idle_child_crash():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {PassThrough} = require("node:stream");

const children = [];
const writes = [];
const runnerPath = require.resolve("./npm/lib/python-runner");
require.cache[runnerPath] = {
  id: runnerPath,
  filename: runnerPath,
  loaded: true,
  exports: {
    spawnPythonModule() {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.stdin = new PassThrough();
      child.stdin.on("data", (chunk) => {
        writes.push({child: children.indexOf(child), request: JSON.parse(chunk.toString("utf8"))});
      });
      child.killed = false;
      child.exitCode = null;
      child.signalCode = null;
      child.kill = () => { child.killed = true; };
      children.push(child);
      setImmediate(() => child.stdout.write(JSON.stringify({
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
      }) + "\n"));
      return child;
    },
  },
};

const {createRuntimeSessionClient} = require("./npm/lib/runtime-client");
const client = createRuntimeSessionClient();
const lifecycle = [];
client.subscribe((event) => lifecycle.push(event));

async function waitFor(predicate) {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.ok(predicate(), "condition did not become true");
}

async function main() {
  await waitFor(() => lifecycle.filter((event) => event.type === "runtime_ready").length === 1);
  children[0].emit("close", 9);
  await waitFor(() => children.length === 2);
  await waitFor(() => lifecycle.filter((event) => event.type === "runtime_ready").length === 2);

  const runEvents = [];
  client.run("after recovery", (event) => runEvents.push(event));
  await waitFor(() => writes.length === 1);
  assert.equal(writes[0].child, 1);
  assert.equal(writes[0].request.goal, "after recovery");

  children[1].stdout.write(JSON.stringify({
    type: "run_completed",
    status: "done",
    answer: "ok",
    payload: {},
  }) + "\n");
  await waitFor(() => runEvents.at(-1)?.type === "run_completed");

  children[1].stderr.write("second crash\n");
  children[1].emit("close", 9);
  await waitFor(() => lifecycle.some((event) => event.type === "client_failed"));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(children.length, 2);
  assert.match(lifecycle.at(-1).message, /second crash/);
  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_npm_runtime_client_fails_active_run_then_recovers_child():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {EventEmitter} = require("node:events");
const {PassThrough} = require("node:stream");

const children = [];
const writes = [];
const runnerPath = require.resolve("./npm/lib/python-runner");
require.cache[runnerPath] = {
  id: runnerPath,
  filename: runnerPath,
  loaded: true,
  exports: {
    spawnPythonModule() {
      const child = new EventEmitter();
      child.stdout = new PassThrough();
      child.stderr = new PassThrough();
      child.stdin = new PassThrough();
      child.stdin.on("data", (chunk) => {
        writes.push({child: children.indexOf(child), request: JSON.parse(chunk.toString("utf8"))});
      });
      child.killed = false;
      child.exitCode = null;
      child.signalCode = null;
      child.kill = () => { child.killed = true; };
      children.push(child);
      setImmediate(() => child.stdout.write(JSON.stringify({
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
      }) + "\n"));
      return child;
    },
  },
};

const {createRuntimeSessionClient} = require("./npm/lib/runtime-client");
const client = createRuntimeSessionClient();
const lifecycle = [];
client.subscribe((event) => lifecycle.push(event));

async function waitFor(predicate) {
  const deadline = Date.now() + 1000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.ok(predicate(), "condition did not become true");
}

async function main() {
  await waitFor(() => lifecycle.some((event) => event.type === "runtime_ready"));
  const firstEvents = [];
  client.run("crashing run", (event) => firstEvents.push(event));
  await waitFor(() => writes.length === 1);
  children[0].stderr.write("runtime worker crashed\n");
  children[0].emit("close", 17);

  await waitFor(() => firstEvents.some((event) => event.type === "client_failed"));
  assert.match(firstEvents.at(-1).message, /runtime worker crashed/);
  await waitFor(() => children.length === 2);
  await waitFor(() => lifecycle.filter((event) => event.type === "runtime_ready").length === 2);

  const secondEvents = [];
  client.run("retry after crash", (event) => secondEvents.push(event));
  await waitFor(() => writes.length === 2);
  assert.equal(writes[1].child, 1);
  assert.equal(writes[1].request.goal, "retry after crash");
  children[1].stdout.write(JSON.stringify({
    type: "run_completed",
    status: "done",
    answer: "recovered",
    payload: {},
  }) + "\n");
  await waitFor(() => secondEvents.at(-1)?.type === "run_completed");
  assert.equal(secondEvents.at(-1).answer, "recovered");
  client.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr


def test_npm_bin_scripts_are_executable_node_wrappers():
    for script in (Path("npm/bin/kagent.js"), Path("npm/bin/kagent-serve.js")):
        text = script.read_text(encoding="utf-8")
        assert text.startswith("#!/usr/bin/env node\n")
        assert "runPythonEntrypoint" in text


def test_npm_kagent_bin_prefers_ink_tui_with_classic_fallback():
    text = Path("npm/bin/kagent.js").read_text(encoding="utf-8")

    assert "runKagentInk" in text
    assert "shouldRunInkTui" in text
    assert "--classic" in text
    assert "runPythonEntrypoint(\"kagent\", classicArgs(args))" in text


def test_npm_ink_runner_uses_built_ink_app():
    text = Path("npm/lib/ink-runner.js").read_text(encoding="utf-8")
    client = Path("npm/lib/runtime-client.js").read_text(encoding="utf-8")

    assert "Ink" in text
    assert "React" in text
    assert "kagent" in text
    assert "kagent.cli.stdio_runtime" in client
    assert "run_request" in client


def test_npm_runner_uses_cache_venv_and_env_forwarding():
    runner = Path("npm/lib/python-runner.js").read_text(encoding="utf-8")

    assert "KAGENT_NODE_VENV" in runner
    assert "KAGENT_PYTHON" in runner
    assert '"pip", "install", "--disable-pip-version-check", "--quiet", root' in runner
    assert '{ cwd: root, stdio: "pipe" }' in runner
    assert '"-e", root' not in runner
    assert "env: process.env" in runner


def test_npm_runner_reinstalls_cached_python_runtime_when_sources_change():
    runner = Path("npm/lib/python-runner.js").read_text(encoding="utf-8")

    assert "sourceHash" in runner
    assert 'crypto.createHash("sha256")' in runner
    assert '"src"' in runner
    assert "sourceFingerprintPaths(root)" in runner
    assert "actual.sourceHash === expected.sourceHash" in runner


def test_npm_runner_checks_github_for_interactive_self_update():
    runner = Path("npm/lib/python-runner.js").read_text(encoding="utf-8")

    assert "https://raw.githubusercontent.com/OpenLucasKaka/Kagent/main/package.json" in runner
    assert "https://api.github.com/repos/OpenLucasKaka/Kagent/commits/main" in runner
    assert "KAGENT_NO_SELF_UPDATE" in runner
    assert "process.stdin.isTTY" in runner
    assert "Update now? [Y/n]" in runner
    assert "readline.createInterface" in runner
    assert "fs.readSync(0" not in runner
    assert 'const GITHUB_INSTALL_SPEC = "github:OpenLucasKaka/Kagent"' in runner
    assert '"npm", ["install", "-g", GITHUB_INSTALL_SPEC]' in runner
    assert "selfUpdateStatePath" in runner
    assert 'prompted: "true"' in runner
    assert runner.index('prompted: "true"') < runner.index(
        "if (!(await promptForSelfUpdate"
    )


def test_npm_kagent_version_does_not_bootstrap_python_runtime(tmp_path):
    node = shutil.which("node")
    if node is None:
        return
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))

    completed = subprocess.run(
        [node, "npm/bin/kagent.js", "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={
            "KAGENT_NODE_VENV": str(tmp_path / "empty-cache"),
            "KAGENT_NO_SELF_UPDATE": "1",
            "PATH": "",
        },
    )

    assert json.loads(completed.stdout) == {"version": package_json["version"]}
    assert completed.stderr == ""


def test_npm_kagent_version_output_file_does_not_bootstrap_python_runtime(tmp_path):
    node = shutil.which("node")
    if node is None:
        return
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    output_path = tmp_path / "version.json"

    completed = subprocess.run(
        [node, "npm/bin/kagent.js", "--version", "--output", str(output_path)],
        check=True,
        capture_output=True,
        text=True,
        env={
            "KAGENT_NODE_VENV": str(tmp_path / "empty-cache"),
            "KAGENT_NO_SELF_UPDATE": "1",
            "PATH": "",
        },
    )

    assert completed.stdout == ""
    assert completed.stderr == ""
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "version": package_json["version"]
    }

    reversed_output_path = tmp_path / "version-reversed.json"
    subprocess.run(
        [node, "npm/bin/kagent.js", "--output", str(reversed_output_path), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={
            "KAGENT_NODE_VENV": str(tmp_path / "empty-cache"),
            "KAGENT_NO_SELF_UPDATE": "1",
            "PATH": "",
        },
    )
    assert json.loads(reversed_output_path.read_text(encoding="utf-8")) == {
        "version": package_json["version"]
    }


def test_npm_runner_semver_comparison_handles_multi_digit_segments():
    node = shutil.which("node")
    if node is None:
        return

    script = """
const { _internals } = require("./npm/lib/python-runner");
if (!_internals.isNewerVersion("0.1.10", "0.1.9")) {
  throw new Error("0.1.10 should be newer than 0.1.9");
}
if (_internals.isNewerVersion("0.1.9", "0.1.10")) {
  throw new Error("0.1.9 should not be newer than 0.1.10");
}
if (_internals.isNewerVersion("0.1.0", "0.1.0")) {
  throw new Error("equal versions should not be newer");
}
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_runner_does_not_prompt_for_same_version_github_updates():
    node = shutil.which("node")
    if node is None:
        return

    script = """
const { _internals } = require("./npm/lib/python-runner");
if (_internals.hasSelfUpdate(
  {version: "0.1.1", headSha: "new", sourceFingerprint: "remote"},
  "0.1.1",
  {remoteHeadSha: "old", remoteVersion: "0.1.1"},
  "same"
)) {
  throw new Error("same source fingerprint should not prompt even with old state");
}
if (_internals.hasSelfUpdate(
  {
    version: "0.1.1",
    headSha: "stale",
    sourceFingerprint: "remote",
    isNewerSameVersion: false
  },
  "0.1.1",
  {remoteHeadSha: "stale", remoteVersion: "0.1.1"},
  "local"
)) {
  throw new Error("stale same-version GitHub head should not prompt");
}
if (_internals.hasSelfUpdate(
  {version: "0.1.1", headSha: "same"},
  "0.1.1",
  {remoteHeadSha: "same"},
  "same"
)) {
  throw new Error("same GitHub head should not prompt");
}
if (_internals.hasSelfUpdate(
  {version: "0.1.1", headSha: "latest"},
  "0.1.1",
  {},
  "local"
)) {
  throw new Error("same version without prior state should not prompt");
}
if (!_internals.hasSelfUpdate(
  {version: "0.1.2", headSha: "same"},
  "0.1.1",
  {remoteHeadSha: "same"},
  "same"
)) {
  throw new Error("newer package version should prompt");
}
if (_internals.hasSelfUpdate(
  {version: "0.1.2", headSha: "new"},
  "0.1.2",
  {remoteHeadSha: "old", remoteVersion: "0.1.1"},
  "same"
)) {
  throw new Error("old version state should not force a same-version prompt after package update");
}
"""
    subprocess.run([node, "-e", script], check=True)


def test_npm_wrapper_javascript_syntax_is_valid_when_node_is_available():
    node = shutil.which("node")
    if node is None:
        return

    for script in (
        "npm/bin/kagent.js",
        "npm/bin/kagent-serve.js",
        "npm/lib/ink-runner.js",
        "npm/lib/python-runner.js",
    ):
        subprocess.run([node, "--check", script], check=True)
