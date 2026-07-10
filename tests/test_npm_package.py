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


def test_npm_ink_runtime_keeps_one_session_and_hides_internal_tool_names():
    app = Path("npm/src/App.tsx").read_text(encoding="utf-8")
    client = Path("npm/src/runtime-client.ts").read_text(encoding="utf-8")

    assert "createRuntimeSessionClient" in app
    assert "respondToApproval" in app
    assert "runtime.command" in app
    assert "Permission required" in app
    assert "approval.title" in app
    assert "approval.target" in app
    assert "approval.tool" not in app
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
  ["a", "a", true],
  ["e", "e", true],
  ["c", "c", true],
  ["你", undefined, false],
  ["z", "z", false],
  ["", "left", false],
  ["", "backspace", false],
  ["", "return", false],
  ["first second", undefined, false],
  ["third fourth 👍", undefined, false],
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
assert.deepEqual([editor().value, editor().cursor], ["X你a!Yfirst second", 17]);
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
  [states[9].editor.value, states[9].editor.cursor],
  ["x👍🏽", 2],
);
inputEvents.emit("input", "e");
inputEvents.emit("input", "\u0301");
assert.deepEqual(
  [states[9].editor.value, states[9].editor.cursor],
  ["x👍🏽e\u0301", 3],
);

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
    assert '"pip", "install", root' in runner
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
