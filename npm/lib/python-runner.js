"use strict";

const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");
const readline = require("readline");

const GITHUB_PACKAGE_JSON_URL = "https://raw.githubusercontent.com/OpenLucasKaka/Kagent/main/package.json";
const GITHUB_HEAD_URL = "https://api.github.com/repos/OpenLucasKaka/Kagent/commits/main";
const GITHUB_INSTALL_SPEC = "github:OpenLucasKaka/Kagent";
const SELF_UPDATE_TIMEOUT_MS = 3000;

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

function metadataCacheRoot() {
  const base = process.env.XDG_CACHE_HOME || path.join(os.homedir(), ".cache");
  return path.join(base, "kagent");
}

function selfUpdateStatePath() {
  return path.join(metadataCacheRoot(), "npm-self-update.json");
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
  throw new Error("kagent requires Python 3.9+. Install python3 or set KAGENT_PYTHON.");
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

function envFlagEnabled(value) {
  if (value === undefined || value === null || value === "") {
    return false;
  }
  return !["0", "false", "no"].includes(String(value).toLowerCase());
}

function shouldCheckSelfUpdate(env, stdin) {
  return !envFlagEnabled(env.KAGENT_NO_SELF_UPDATE) && Boolean(stdin.isTTY);
}

function parseVersion(version) {
  const [mainPart, prerelease = ""] = String(version).replace(/^v/, "").split("-", 2);
  const parts = mainPart.split(".").map((part) => {
    const value = Number(part);
    return Number.isInteger(value) && value >= 0 ? value : 0;
  });
  while (parts.length < 3) {
    parts.push(0);
  }
  return {
    parts: parts.slice(0, 3),
    prerelease
  };
}

function isNewerVersion(candidate, current) {
  const candidateVersion = parseVersion(candidate);
  const currentVersion = parseVersion(current);
  for (let index = 0; index < 3; index += 1) {
    if (candidateVersion.parts[index] > currentVersion.parts[index]) {
      return true;
    }
    if (candidateVersion.parts[index] < currentVersion.parts[index]) {
      return false;
    }
  }
  if (candidateVersion.prerelease === currentVersion.prerelease) {
    return false;
  }
  if (candidateVersion.prerelease === "") {
    return currentVersion.prerelease !== "";
  }
  if (currentVersion.prerelease === "") {
    return false;
  }
  return candidateVersion.prerelease > currentVersion.prerelease;
}

function fetchText(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const request = https.get(url, { headers: { "User-Agent": "kagent-self-update" } }, (response) => {
      if (response.statusCode >= 300 && response.statusCode < 400 && response.headers.location) {
        response.resume();
        fetchText(response.headers.location, timeoutMs).then(resolve, reject);
        return;
      }
      if (response.statusCode !== 200) {
        response.resume();
        reject(new Error(`GitHub returned HTTP ${response.statusCode}`));
        return;
      }
      response.setEncoding("utf8");
      let body = "";
      response.on("data", (chunk) => {
        body += chunk;
      });
      response.on("end", () => {
        resolve(body);
      });
    });
    request.setTimeout(timeoutMs, () => {
      request.destroy(new Error("GitHub update check timed out"));
    });
    request.on("error", reject);
  });
}

async function fetchLatestGitHubVersion() {
  const body = await fetchText(GITHUB_PACKAGE_JSON_URL, SELF_UPDATE_TIMEOUT_MS);
  const packageJson = JSON.parse(body);
  if (typeof packageJson.version !== "string" || packageJson.version.trim() === "") {
    throw new Error("GitHub package.json does not declare a version");
  }
  return packageJson.version;
}

async function fetchLatestGitHubHeadSha() {
  const body = await fetchText(GITHUB_HEAD_URL, SELF_UPDATE_TIMEOUT_MS);
  const payload = JSON.parse(body);
  const sha = String(payload.sha || "").trim();
  if (!sha) {
    throw new Error("GitHub commit response does not declare a sha");
  }
  return sha;
}

async function fetchLatestGitHubUpdateInfo() {
  const version = await fetchLatestGitHubVersion();
  const headSha = await fetchLatestGitHubHeadSha();
  return { version, headSha };
}

function readSelfUpdateState() {
  const statePath = selfUpdateStatePath();
  if (!fs.existsSync(statePath)) {
    return {};
  }
  try {
    const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
    return state && typeof state === "object" ? state : {};
  } catch (_error) {
    return {};
  }
}

function writeSelfUpdateState(state) {
  const statePath = selfUpdateStatePath();
  fs.mkdirSync(path.dirname(statePath), { recursive: true, mode: 0o700 });
  fs.writeFileSync(statePath, `${JSON.stringify(state, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600
  });
}

function latestSelfUpdateState(latest, extra) {
  return Object.assign({
    remoteHeadSha: latest.headSha,
    remoteVersion: latest.version,
    checkedAt: new Date().toISOString()
  }, extra || {});
}

function hasSelfUpdate(latest, currentVersion, _state) {
  return isNewerVersion(latest.version, currentVersion);
}

function promptForSelfUpdate(currentVersion, latest) {
  const shortSha = latest.headSha ? ` (${latest.headSha.slice(0, 7)})` : "";
  const prompt =
    `kagent ${latest.version}${shortSha} is available. Current version: ${currentVersion}.\n` +
    "Update now? [Y/n] ";
  return new Promise((resolve) => {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stderr
    });
    rl.question(prompt, (answer) => {
      rl.close();
      const normalized = String(answer || "").trim().toLowerCase();
      resolve(normalized === "" || normalized === "y" || normalized === "yes");
    });
  });
}

function restartEntrypoint(commandName, args) {
  const result = childProcess.spawnSync(commandName, args, {
    env: process.env,
    stdio: "inherit",
    shell: process.platform === "win32"
  });
  if (result.error) {
    throw result.error;
  }
  process.exit(result.status === null ? 1 : result.status);
}

async function maybeSelfUpdate(root, currentVersion, commandName, args) {
  if (envFlagEnabled(process.env.KAGENT_NO_SELF_UPDATE) || !process.stdin.isTTY) {
    return false;
  }

  let latest;
  let state;
  try {
    latest = await fetchLatestGitHubUpdateInfo();
    state = readSelfUpdateState();
  } catch (error) {
    process.stderr.write(`kagent: update check skipped: ${error.message}\n`);
    return false;
  }

  if (!hasSelfUpdate(latest, currentVersion, state)) {
    writeSelfUpdateState(latestSelfUpdateState(latest));
    return false;
  }

  writeSelfUpdateState(latestSelfUpdateState(latest, {
    prompted: "true"
  }));

  if (!(await promptForSelfUpdate(currentVersion, latest))) {
    writeSelfUpdateState(latestSelfUpdateState(latest, {
      skipped: "true"
    }));
    return false;
  }

  process.stderr.write(`kagent: installing ${GITHUB_INSTALL_SPEC}\n`);
  try {
    runChecked("npm", ["install", "-g", GITHUB_INSTALL_SPEC], { cwd: root });
  } catch (error) {
    writeSelfUpdateState(latestSelfUpdateState(latest, {
      failed: "true"
    }));
    process.stderr.write(`kagent: update failed: ${error.message}; continuing with ${currentVersion}\n`);
    return false;
  }
  writeSelfUpdateState(latestSelfUpdateState(latest, {
    installed: "true"
  }));
  process.stderr.write("kagent: update installed; restarting\n");
  restartEntrypoint(commandName, args);
  return true;
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
    const relativePath = path.posix.join(relativeDirectory, entry.name);
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
    process.stderr.write(`kagent: preparing Python runtime in ${venvDir}\n`);
    runChecked(python, ["-m", "venv", venvDir], { cwd: root });
  }

  process.stderr.write("kagent: installing Python runtime package\n");
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

async function runPythonEntrypoint(commandName, args) {
  try {
    const root = packageRoot();
    const version = readPackageVersion(root);
    if (await maybeSelfUpdate(root, version, commandName, args)) {
      return;
    }
    const venvDir = ensureVenv(root, version);
    spawnEntrypoint(venvDir, commandName, args);
  } catch (error) {
    process.stderr.write(`kagent failed to start: ${error.message}\n`);
    process.exit(1);
  }
}

module.exports = {
  runPythonEntrypoint,
  _internals: {
    hasSelfUpdate,
    isNewerVersion,
    shouldCheckSelfUpdate
  }
};
