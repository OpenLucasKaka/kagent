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
    assert "run_completed" in combined
    assert "kagent.cli.stdio_runtime" in combined
    assert "--classic" not in Path("npm/src/runtime-client.ts").read_text(encoding="utf-8")


def test_npm_ink_runtime_keeps_one_session_and_hides_internal_tool_names():
    app = Path("npm/src/App.tsx").read_text(encoding="utf-8")
    client = Path("npm/src/runtime-client.ts").read_text(encoding="utf-8")

    assert "createRuntimeSessionClient" in app
    assert "respondToApproval" in app
    assert "Permission required" in app
    assert "approval.title" in app
    assert "approval.target" in app
    assert "approval.tool" not in app
    assert "child.stdin.end" not in client
    assert "approval_response" in client
    assert "runtime session is busy" in client


def test_npm_ink_editor_handles_unicode_graphemes():
    node = shutil.which("node")
    if node is None:
        return

    script = r"""
const assert = require("node:assert/strict");
const {
  applyInput,
  deleteBeforeCursor,
  moveCursor,
  splitGraphemes,
} = require("./npm/lib/App");

assert.deepEqual(splitGraphemes("你👍🏽e\u0301"), ["你", "👍🏽", "e\u0301"]);

let state = applyInput({value: "", cursor: 0}, "你好👍🏽");
assert.deepEqual(state, {value: "你好👍🏽", cursor: 3});

state = moveCursor(state, -1);
state = applyInput(state, "，");
assert.deepEqual(state, {value: "你好，👍🏽", cursor: 3});

state = deleteBeforeCursor(state);
assert.deepEqual(state, {value: "你好👍🏽", cursor: 2});

state = applyInput(state, "e\u0301\x7fA");
assert.deepEqual(state, {value: "你好A👍🏽", cursor: 3});
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
