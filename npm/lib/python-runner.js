"use strict";

const childProcess = require("child_process");
const crypto = require("crypto");
const fs = require("fs");
const https = require("https");
const path = require("path");
const readline = require("readline");

const { kagentCachePath, resolveKagentHome } = require("./kagent-home");

const GITHUB_PACKAGE_JSON_URL = "https://raw.githubusercontent.com/OpenLucasKaka/Kagent/main/package.json";
const GITHUB_HEAD_URL = "https://api.github.com/repos/OpenLucasKaka/Kagent/commits/main";
const GITHUB_INSTALL_SPEC = "github:OpenLucasKaka/Kagent";
const SELF_UPDATE_TIMEOUT_MS = 3000;
const SECURE_FILESYSTEM_HELPER = String.raw`
import errno
import os
import stat
import sys


DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def fail(message):
    raise RuntimeError(message)


def path_parts(target):
    if not os.path.isabs(target):
        fail("managed path must be absolute")
    normalized = os.path.normpath(target)
    parts = [part for part in normalized.split(os.sep) if part]
    if not parts:
        fail("refusing managed filesystem root")
    return parts


def open_directory(target, create_missing):
    parts = path_parts(target)
    current_fd = os.open(os.sep, DIRECTORY_FLAGS)
    try:
        for part in parts:
            try:
                next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=current_fd)
            except FileNotFoundError:
                if not create_missing:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                except FileExistsError:
                    pass
                next_fd = os.open(part, DIRECTORY_FLAGS, dir_fd=current_fd)
            except OSError as error:
                if error.errno in (errno.ELOOP, errno.ENOTDIR):
                    fail(f"refusing symbolic link or non-directory in managed path: {target}")
                raise
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def ensure_directory(target):
    directory_fd = open_directory(target, True)
    try:
        if not stat.S_ISDIR(os.fstat(directory_fd).st_mode):
            fail(f"managed path is not a directory: {target}")
        os.fchmod(directory_fd, 0o700)
    finally:
        os.close(directory_fd)


def write_file(target):
    parent, name = os.path.split(os.path.normpath(target))
    if not name or name in (".", ".."):
        fail(f"managed path is not a file: {target}")
    parent_fd = open_directory(parent, False)
    file_fd = None
    try:
        try:
            file_fd = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent_fd,
            )
        except OSError as error:
            if error.errno in (errno.ELOOP, errno.ENOTDIR):
                fail(f"refusing symbolic link in managed path: {target}")
            raise
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            fail(f"managed path is not a file: {target}")
        os.fchmod(file_fd, 0o600)
        body = sys.stdin.buffer.read()
        offset = 0
        while offset < len(body):
            offset += os.write(file_fd, body[offset:])
        os.fchmod(file_fd, 0o600)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


try:
    operation, target = sys.argv[1:3]
    if operation == "ensure-directory":
        ensure_directory(target)
    elif operation == "write-file":
        write_file(target)
    else:
        fail(f"unsupported secure filesystem operation: {operation}")
except BaseException as error:
    sys.stderr.write(f"{error}\n")
    raise SystemExit(1)
`;

function packageRoot() {
  return path.resolve(__dirname, "..", "..");
}

function readPackageVersion(root) {
  const packageJsonPath = path.join(root, "package.json");
  const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, "utf8"));
  return packageJson.version;
}

function maybePrintNodeHandledOutput(commandName, args, version) {
  if (commandName !== "kagent") {
    return false;
  }
  const versionOutput = versionOutputTarget(args);
  if (versionOutput === null) {
    return false;
  }
  const body = `${JSON.stringify({ version }, null, 2)}\n`;
  if (versionOutput) {
    fs.writeFileSync(versionOutput, body, { encoding: "utf8" });
  } else {
    process.stdout.write(body);
  }
  return true;
}

function versionOutputTarget(args) {
  if (args.length === 1 && args[0] === "--version") {
    return "";
  }
  if (args.length === 3 && args[0] === "--version" && args[1] === "--output") {
    return args[2];
  }
  if (args.length === 3 && args[0] === "--output" && args[2] === "--version") {
    return args[1];
  }
  return null;
}

function cacheRoot(env = process.env) {
  if (env.KAGENT_NODE_VENV) {
    return path.resolve(env.KAGENT_NODE_VENV);
  }
  return kagentCachePath("npm-python", env);
}

function metadataCacheRoot(env = process.env) {
  return path.dirname(kagentCachePath("npm-python", env));
}

function selfUpdateStatePath(env = process.env) {
  return path.join(metadataCacheRoot(env), "npm-self-update.json");
}

function rejectSymlinks(targetPath) {
  const resolved = path.resolve(targetPath);
  const parsed = path.parse(resolved);
  const parts = resolved.slice(parsed.root.length).split(path.sep).filter(Boolean);
  let current = parsed.root;
  for (const part of parts) {
    current = path.join(current, part);
    let stat;
    try {
      stat = fs.lstatSync(current);
    } catch (error) {
      if (error.code === "ENOENT") {
        return;
      }
      throw error;
    }
    if (stat.isSymbolicLink()) {
      throw new Error(`refusing symbolic link in managed path: ${current}`);
    }
  }
}

function ensurePrivateDirectory(directory) {
  const resolved = path.resolve(directory);
  runSecureFilesystemOperation("ensure-directory", resolved);
  return directory;
}

function ensureCacheRoot(env = process.env) {
  if (env.KAGENT_NODE_VENV) {
    return ensurePrivateDirectory(path.resolve(env.KAGENT_NODE_VENV));
  }
  const home = ensurePrivateDirectory(resolveKagentHome(env));
  const cache = ensurePrivateDirectory(path.join(home, "cache"));
  return ensurePrivateDirectory(path.join(cache, "npm-python"));
}

function ensureMetadataCacheRoot(env = process.env) {
  const home = ensurePrivateDirectory(resolveKagentHome(env));
  return ensurePrivateDirectory(path.join(home, "cache"));
}

function writePrivateFile(filePath, body) {
  runSecureFilesystemOperation("write-file", path.resolve(filePath), body);
}

function runSecureFilesystemOperation(operation, targetPath, body = "") {
  const python = findPython();
  const result = childProcess.spawnSync(
    python,
    ["-c", SECURE_FILESYSTEM_HELPER, operation, targetPath],
    {
      encoding: "utf8",
      env: process.env,
      input: body,
      stdio: ["pipe", "pipe", "pipe"]
    }
  );
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const detail = String(result.stderr || result.stdout || "").trim();
    const suffix = detail ? `: ${detail.slice(-4000)}` : "";
    throw new Error(
      `secure filesystem ${operation} failed for ${targetPath}${suffix}`
    );
  }
}

function privateFileStat(filePath) {
  let stat;
  try {
    stat = fs.lstatSync(filePath);
  } catch (error) {
    if (error.code === "ENOENT") {
      return null;
    }
    throw error;
  }
  if (stat.isSymbolicLink()) {
    throw new Error(`refusing symbolic link in managed path: ${filePath}`);
  }
  if (!stat.isFile()) {
    throw new Error(`managed path is not a file: ${filePath}`);
  }
  return stat;
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
    encoding: "utf8",
    stdio: options.stdio || "inherit"
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const detail = [result.stdout, result.stderr]
      .filter((value) => typeof value === "string" && value.trim())
      .join("\n")
      .trim();
    const suffix = detail ? `\n${detail.slice(-4000)}` : "";
    throw new Error(
      `${command} ${args.join(" ")} failed with exit code ${result.status}${suffix}`
    );
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

function readSelfUpdateState(env = process.env) {
  const statePath = selfUpdateStatePath(env);
  rejectSymlinks(statePath);
  if (!privateFileStat(statePath)) {
    return {};
  }
  try {
    const state = JSON.parse(fs.readFileSync(statePath, "utf8"));
    return state && typeof state === "object" ? state : {};
  } catch (_error) {
    return {};
  }
}

function writeSelfUpdateState(state, env = process.env) {
  const statePath = path.join(ensureMetadataCacheRoot(env), "npm-self-update.json");
  writePrivateFile(statePath, `${JSON.stringify(state, null, 2)}\n`);
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

function installMarker(root, version, dependencyFingerprint) {
  return {
    packageRoot: root,
    version,
    dependencyHash: dependencyFingerprint,
    sourceHash: sourceHash(root)
  };
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function projectTable(pyproject) {
  const match = pyproject.match(/^\s*\[project\]\s*(?:#.*)?$/m);
  if (!match) {
    throw new Error("pyproject.toml does not declare [project]");
  }
  const bodyStart = match.index + match[0].length;
  const remaining = pyproject.slice(bodyStart);
  const nextTable = remaining.search(/^\s*\[/m);
  return nextTable === -1 ? remaining : remaining.slice(0, nextTable);
}

function tomlString(value) {
  if (value.startsWith('"')) {
    return JSON.parse(value);
  }
  return value.slice(1, -1);
}

function projectString(project, key) {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = project.match(
    new RegExp(`^\\s*${escapedKey}\\s*=\\s*("(?:\\\\.|[^"\\\\])*"|'[^']*')\\s*(?:#.*)?$`, "m")
  );
  if (!match) {
    throw new Error(`pyproject.toml [project] does not declare ${key}`);
  }
  return tomlString(match[1]);
}

function projectStringArray(project, key) {
  const escapedKey = key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const assignment = new RegExp(`^\\s*${escapedKey}\\s*=\\s*\\[`, "m").exec(project);
  if (!assignment) {
    throw new Error(`pyproject.toml [project] does not declare ${key}`);
  }
  const values = [];
  let index = assignment.index + assignment[0].length;
  while (index < project.length) {
    const character = project[index];
    if (character === "]") {
      return values;
    }
    if (character === "#") {
      while (index < project.length && project[index] !== "\n") index += 1;
      continue;
    }
    if (character === '"' || character === "'") {
      const quote = character;
      const start = index;
      index += 1;
      while (index < project.length) {
        if (quote === '"' && project[index] === "\\") {
          index += 2;
          continue;
        }
        if (project[index] === quote) {
          index += 1;
          values.push(tomlString(project.slice(start, index)));
          break;
        }
        index += 1;
      }
      if (project[index - 1] !== quote) {
        throw new Error(`unterminated string in [project].${key}`);
      }
      continue;
    }
    index += 1;
  }
  throw new Error(`unterminated array in [project].${key}`);
}

function dependencyHash(root) {
  const pyproject = fs.readFileSync(path.join(root, "pyproject.toml"), "utf8");
  const project = projectTable(pyproject);
  return sha256(JSON.stringify({
    requiresPython: projectString(project, "requires-python"),
    dependencies: projectStringArray(project, "dependencies")
  }));
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

function readMarker(venvDir) {
  const pathToMarker = markerPath(venvDir);
  if (!privateFileStat(pathToMarker)) {
    return null;
  }
  try {
    return JSON.parse(fs.readFileSync(pathToMarker, "utf8"));
  } catch (_error) {
    return null;
  }
}

function markerMatches(actual, expected) {
  return Boolean(actual) &&
    actual.packageRoot === expected.packageRoot &&
    actual.version === expected.version &&
    actual.dependencyHash === expected.dependencyHash &&
    actual.sourceHash === expected.sourceHash;
}

function writeMarker(venvDir, marker) {
  writePrivateFile(markerPath(venvDir), `${JSON.stringify(marker, null, 2)}\n`);
}

function pythonRuntimeIdentity(python) {
  const result = childProcess.spawnSync(
    python,
    ["-c", "import json, sys; print(json.dumps({'implementation': sys.implementation.name, 'major': sys.version_info[0], 'minor': sys.version_info[1]}))"],
    { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }
  );
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`failed to identify Python runtime: ${String(result.stderr || "").trim()}`);
  }
  const identity = JSON.parse(result.stdout);
  if (!/^[A-Za-z0-9_-]+$/.test(identity.implementation) ||
      !Number.isInteger(identity.major) || !Number.isInteger(identity.minor)) {
    throw new Error("Python runtime returned an invalid identity");
  }
  return identity;
}

function runtimeCacheDirectory(cache, identity, platform, arch, dependencyFingerprint) {
  const abi = `${identity.implementation}-${identity.major}.${identity.minor}`;
  return path.join(cache, abi, `${platform}-${arch}`, dependencyFingerprint);
}

function ensureVenv(root, version, options = {}) {
  const python = options.python || findPython();
  const identity = options.pythonIdentity || pythonRuntimeIdentity(python);
  const dependencyFingerprint = dependencyHash(root);
  const cache = options.cacheRoot || ensureCacheRoot();
  const platform = options.platform || process.platform;
  const arch = options.arch || process.arch;
  const venvDir = runtimeCacheDirectory(cache, identity, platform, arch, dependencyFingerprint);
  const ensureDirectory = options.ensurePrivateDirectory || ensurePrivateDirectory;
  const checkedRun = options.runChecked || runChecked;
  const markerWriter = options.writeMarker || writeMarker;
  ensureDirectory(venvDir);
  const expectedMarker = installMarker(root, version, dependencyFingerprint);
  const pythonPath = venvPythonPath(venvDir);
  const actualMarker = readMarker(venvDir);
  const hadPython = fs.existsSync(pythonPath);
  if (hadPython && markerMatches(actualMarker, expectedMarker)) {
    return venvDir;
  }

  if (!hadPython) {
    process.stderr.write(`kagent: preparing Python runtime in ${venvDir}\n`);
    const venvArgs = ["-m", "venv"];
    if (actualMarker) {
      venvArgs.push("--clear");
    }
    venvArgs.push(venvDir);
    checkedRun(python, venvArgs, { cwd: root });
  }

  process.stderr.write("kagent: preparing Python runtime\n");
  const sourceOnlyInstall = hadPython && actualMarker &&
    actualMarker.dependencyHash === dependencyFingerprint;
  const installArgs = ["-m", "pip", "install"];
  if (sourceOnlyInstall) {
    installArgs.push("--no-deps");
  }
  installArgs.push("--disable-pip-version-check", "--quiet", root);
  checkedRun(
    pythonPath,
    installArgs,
    { cwd: root, stdio: "pipe" }
  );
  markerWriter(venvDir, expectedMarker);
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

function ensurePythonRuntime() {
  const root = packageRoot();
  const version = readPackageVersion(root);
  const venvDir = ensureVenv(root, version);
  return {
    root,
    version,
    venvDir,
    pythonPath: venvPythonPath(venvDir)
  };
}

function spawnPythonModule(moduleName, args, options) {
  const runtime = ensurePythonRuntime();
  return childProcess.spawn(
    runtime.pythonPath,
    ["-m", moduleName].concat(args || []),
    Object.assign(
      {
        cwd: runtime.root,
        env: process.env,
        stdio: ["pipe", "pipe", "pipe"]
      },
      options || {}
    )
  );
}

async function runPythonEntrypoint(commandName, args) {
  try {
    const root = packageRoot();
    const version = readPackageVersion(root);
    if (maybePrintNodeHandledOutput(commandName, args, version)) {
      return;
    }
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
  ensurePythonRuntime,
  runPythonEntrypoint,
  spawnPythonModule,
  _internals: {
    cacheRoot,
    dependencyHash,
    ensureCacheRoot,
    ensurePrivateDirectory,
    ensureVenv,
    hasSelfUpdate,
    isNewerVersion,
    metadataCacheRoot,
    maybePrintNodeHandledOutput,
    readSelfUpdateState,
    shouldCheckSelfUpdate,
    sourceHash,
    writeSelfUpdateState
  }
};
