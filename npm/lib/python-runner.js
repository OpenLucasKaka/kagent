"use strict";

const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const os = require("os");
const path = require("path");

function packageRoot() {
  return path.resolve(__dirname, "..", "..");
}

function readPackageVersion(root) {
  const packageJsonPath = path.join(root, "package.json");
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
  return packageJson.version;
}

function cacheRoot() {
  if (process.env.KAGENT_NODE_VENV) {
    return path.resolve(process.env.KAGENT_NODE_VENV);
  }
  const base = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  return path.join(base, "kagent", "npm-python");
}

function candidatePythons() {
  const configured = process.env.KAGENT_PYTHON ? [process.env.KAGENT_PYTHON] : [];
  return configured.concat(["python3", "python"]);
}

function commandWorks(command, args) {
  const result = childProcess.spawnSync(command, args, {
    encoding: "utf8",
    stdio: "ignore"
  });
  return result.status === 0;
}

function findPython() {
  for (const command of candidatePythons()) {
    if (commandWorks(command, ["-c", "import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)"])) {
      return command;
    }
  }
  throw new Error("Kagent requires Python 3.9+. Install python3 or set KAGENT_PYTHON.");
}

function runChecked(command, args, options) {
  const result = childProcess.spawnSync(command, args, {
    cwd: options.cwd,
    env: process.env,
    stdio: options.stdio || "inherit"
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(" ")} failed with exit code ${result.status}`);
  }
}

function executablePath(venvDir, name) {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", `${name}.exe`);
  }
  return path.join(venvDir, "bin", name);
}

function venvPythonPath(venvDir) {
  if (process.platform === "win32") {
    return path.join(venvDir, "Scripts", "python.exe");
  }
  return path.join(venvDir, "bin", "python");
}

function markerPath(venvDir) {
  return path.join(venvDir, ".kagent-node-install.json");
}

function installMarker(root, version) {
  return {
    packageRoot: root,
    version,
    sourceHash: sourceHash(root)
  };
}

function sourceHash(root) {
  const hasher = crypto.createHash("sha256");
  for (const relativePath of sourceFingerprintPaths(root)) {
    const absolutePath = path.join(root, relativePath);
    hasher.update(relativePath);
    hasher.update("\0");
    hasher.update(fs.readFileSync(absolutePath));
    hasher.update("\0");
  }
  return hasher.digest("hex");
}

function sourceFingerprintPaths(root) {
  const paths = ["package.json", "pyproject.toml"];
  collectRelativeFiles(path.join(root, "src"), "src", paths);
  paths.sort();
  return paths;
}

function collectRelativeFiles(directory, relativeDirectory, output) {
  if (!fs.existsSync(directory)) {
    return;
  }
  const entries = fs.readdirSync(directory, { withFileTypes: true });
  for (const entry of entries) {
    const relativePath = path.join(relativeDirectory, entry.name);
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      collectRelativeFiles(absolutePath, relativePath, output);
    } else if (entry.isFile()) {
      output.push(relativePath);
    }
  }
}

function markerMatches(venvDir, expected) {
  const pathToMarker = markerPath(venvDir);
  if (!fs.existsSync(pathToMarker)) {
    return false;
  }
  try {
    const actual = JSON.parse(fs.readFileSync(pathToMarker, "utf8"));
    return (
      actual.packageRoot === expected.packageRoot &&
      actual.version === expected.version &&
      actual.sourceHash === expected.sourceHash
    );
  } catch (_error) {
    return false;
  }
}

function writeMarker(venvDir, marker) {
  fs.writeFileSync(markerPath(venvDir), `${JSON.stringify(marker, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600
  });
}

function ensureVenv(root, version) {
  const venvDir = path.join(cacheRoot(), version);
  const expectedMarker = installMarker(root, version);
  const pythonPath = venvPythonPath(venvDir);
  if (fs.existsSync(pythonPath) && markerMatches(venvDir, expectedMarker)) {
    return venvDir;
  }

  fs.mkdirSync(path.dirname(venvDir), { recursive: true, mode: 0o700 });
  fs.mkdirSync(venvDir, { recursive: true, mode: 0o700 });
  fs.chmodSync(venvDir, 0o700);
  if (!fs.existsSync(pythonPath)) {
    const python = findPython();
    process.stderr.write(`Kagent: preparing Python runtime in ${venvDir}\n`);
    runChecked(python, ["-m", "venv", venvDir], { cwd: root });
  }

  process.stderr.write("Kagent: installing Python runtime package\n");
  runChecked(pythonPath, ["-m", "pip", "install", root], { cwd: root });
  writeMarker(venvDir, expectedMarker);
  return venvDir;
}

function spawnEntrypoint(venvDir, commandName, args) {
  const command = executablePath(venvDir, commandName);
  const result = childProcess.spawnSync(command, args, {
    env: process.env,
    stdio: "inherit"
  });
  if (result.error) {
    throw result.error;
  }
  process.exit(result.status === null ? 1 : result.status);
}

function runPythonEntrypoint(commandName, args) {
  try {
    const root = packageRoot();
    const version = readPackageVersion(root);
    const venvDir = ensureVenv(root, version);
    spawnEntrypoint(venvDir, commandName, args);
  } catch (error) {
    process.stderr.write(`Kagent failed to start: ${error.message}\n`);
    process.exit(1);
  }
}

module.exports = {
  runPythonEntrypoint
};
