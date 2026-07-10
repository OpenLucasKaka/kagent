import json
import shutil
import subprocess
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


def test_npm_ink_runner_bridges_to_classic_python_runtime():
    text = Path("npm/lib/ink-runner.js").read_text(encoding="utf-8")

    assert "Ink" in text
    assert "React" in text
    assert "spawn" in text
    assert "--classic" in text
    assert "--runtime" in text
    assert "kagent" in text


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
