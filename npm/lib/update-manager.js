"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.UPDATE_CHECK_TIMEOUT_MS = exports.UPDATE_CHECK_TTL_MS = exports.NPM_REGISTRY_URL = void 0;
exports.resolveUpdateChannel = resolveUpdateChannel;
exports.compareSemVer = compareSemVer;
exports.checkForUpdate = checkForUpdate;
exports.runUpgrade = runUpgrade;
exports.NPM_REGISTRY_URL = "https://registry.npmjs.org/%40openlucaskaka%2Fkagent";
exports.UPDATE_CHECK_TTL_MS = 24 * 60 * 60 * 1_000;
exports.UPDATE_CHECK_TIMEOUT_MS = 3_000;
const INSTALL_ARGS = {
    latest: ["install", "--global", "@openlucaskaka/kagent@latest"],
    next: ["install", "--global", "@openlucaskaka/kagent@next"],
};
class UpdateNetworkError extends Error {
}
class UpdateMetadataError extends Error {
}
function resolveUpdateChannel(env = process.env) {
    const configured = env.KAGENT_UPDATE_CHANNEL?.trim().toLowerCase();
    if (!configured || configured === "stable" || configured === "latest") {
        return "latest";
    }
    if (configured === "beta" || configured === "next") {
        return "next";
    }
    throw new Error(`KAGENT_UPDATE_CHANNEL ${JSON.stringify(configured)} is invalid; expected stable/latest or beta/next`);
}
function compareSemVer(left, right) {
    const parsedLeft = parseSemVer(left);
    const parsedRight = parseSemVer(right);
    for (let index = 0; index < parsedLeft.core.length; index += 1) {
        const compared = compareNumericIdentifier(parsedLeft.core[index], parsedRight.core[index]);
        if (compared !== 0) {
            return compared;
        }
    }
    if (parsedLeft.prerelease === null && parsedRight.prerelease === null) {
        return 0;
    }
    if (parsedLeft.prerelease === null) {
        return 1;
    }
    if (parsedRight.prerelease === null) {
        return -1;
    }
    const identifiers = Math.max(parsedLeft.prerelease.length, parsedRight.prerelease.length);
    for (let index = 0; index < identifiers; index += 1) {
        const leftIdentifier = parsedLeft.prerelease[index];
        const rightIdentifier = parsedRight.prerelease[index];
        if (leftIdentifier === undefined) {
            return -1;
        }
        if (rightIdentifier === undefined) {
            return 1;
        }
        const compared = comparePrereleaseIdentifier(leftIdentifier, rightIdentifier);
        if (compared !== 0) {
            return compared;
        }
    }
    return 0;
}
async function checkForUpdate(options) {
    parseSemVer(options.currentVersion);
    const deps = options.deps ?? {};
    const channel = resolveCheckChannel(options.channel, options.env);
    const now = deps.now?.() ?? new Date();
    const checkedAt = now.toISOString();
    let cacheWarning;
    if (!options.force && deps.readState) {
        let cached;
        try {
            cached = await deps.readState();
        }
        catch (error) {
            cacheWarning = `Unable to read update cache: ${errorMessage(error)}`;
        }
        if (isFreshState(cached, channel, now)) {
            return {
                current: options.currentVersion,
                latest: cached.latest,
                channel,
                updateAvailable: compareSemVer(cached.latest, options.currentVersion) > 0,
                checkedAt: cached.checkedAt,
                skipped: true,
                reason: "ttl",
            };
        }
    }
    let latest;
    try {
        latest = await fetchLatestVersion(channel, deps);
    }
    catch (error) {
        const message = errorMessage(error);
        if (options.force) {
            if (error instanceof UpdateNetworkError) {
                throw new Error(`Unable to check for kagent updates: ${message}`);
            }
            throw error;
        }
        return skippedCheck(options.currentVersion, channel, checkedAt, error instanceof UpdateMetadataError
            ? "metadata-error"
            : "network-error", error);
    }
    const state = { channel, latest, checkedAt };
    try {
        await deps.writeState?.(state);
    }
    catch (error) {
        if (options.force) {
            throw error;
        }
        const warning = `Unable to write update cache: ${errorMessage(error)}`;
        cacheWarning = cacheWarning ? `${cacheWarning}; ${warning}` : warning;
    }
    return {
        current: options.currentVersion,
        latest,
        channel,
        updateAvailable: compareSemVer(latest, options.currentVersion) > 0,
        checkedAt,
        ...(cacheWarning ? { cacheWarning } : {}),
    };
}
function resolveCheckChannel(channel, env) {
    if (channel === undefined) {
        return resolveUpdateChannel(env);
    }
    if (channel === "latest" || channel === "next") {
        return channel;
    }
    throw new Error(`Update channel ${JSON.stringify(channel)} is invalid; expected latest or next`);
}
function skippedCheck(current, channel, checkedAt, reason, error) {
    return {
        current,
        latest: null,
        channel,
        updateAvailable: false,
        checkedAt,
        skipped: true,
        reason,
        error: errorMessage(error),
    };
}
async function runUpgrade(options) {
    const deps = options.deps ?? {};
    const checked = await checkForUpdate({
        currentVersion: options.currentVersion,
        channel: options.channel,
        force: true,
        env: options.env,
        deps,
    });
    if (checked.latest === null) {
        throw new Error("Forced update checks cannot be skipped");
    }
    if (!checked.updateAvailable) {
        return {
            ...checked,
            upgraded: false,
            installedVersion: options.currentVersion,
        };
    }
    if (!deps.runInstall || !deps.readInstalledVersion) {
        throw new Error("runUpgrade requires runInstall and readInstalledVersion dependencies");
    }
    const installArgs = INSTALL_ARGS[checked.channel];
    const installSpec = installArgs[2];
    try {
        await deps.runInstall([...installArgs]);
    }
    catch (error) {
        throw new Error(`Failed to install ${installSpec}: ${errorMessage(error)}`);
    }
    let installedVersion;
    try {
        installedVersion = await deps.readInstalledVersion();
    }
    catch (error) {
        throw new Error(`Unable to verify the installed kagent version: ${errorMessage(error)}`);
    }
    try {
        if (compareSemVer(installedVersion, checked.latest) < 0) {
            throw new Error(`Installed version ${installedVersion} is below expected version ${checked.latest}`);
        }
    }
    catch (error) {
        if (error instanceof Error && /below expected version/.test(error.message)) {
            throw error;
        }
        throw new Error(`Unable to verify installed version ${JSON.stringify(installedVersion)}: ${errorMessage(error)}`);
    }
    return { ...checked, upgraded: true, installedVersion };
}
function parseSemVer(version) {
    const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$/.exec(version);
    if (!match) {
        throw new Error(`Invalid SemVer: ${JSON.stringify(version)}`);
    }
    const prerelease = match[4]?.split(".") ?? null;
    if (prerelease?.some((identifier) => /^\d+$/.test(identifier) && /^0\d/.test(identifier))) {
        throw new Error(`Invalid SemVer: ${JSON.stringify(version)}`);
    }
    return {
        core: [match[1], match[2], match[3]],
        prerelease,
    };
}
function compareNumericIdentifier(left, right) {
    if (left.length !== right.length) {
        return left.length < right.length ? -1 : 1;
    }
    return left === right ? 0 : left < right ? -1 : 1;
}
function comparePrereleaseIdentifier(left, right) {
    const leftNumeric = /^\d+$/.test(left);
    const rightNumeric = /^\d+$/.test(right);
    if (leftNumeric && rightNumeric) {
        return compareNumericIdentifier(left, right);
    }
    if (leftNumeric !== rightNumeric) {
        return leftNumeric ? -1 : 1;
    }
    return left === right ? 0 : left < right ? -1 : 1;
}
function isFreshState(state, channel, now) {
    if (!state || state.channel !== channel) {
        return false;
    }
    const checkedAt = Date.parse(state.checkedAt);
    const age = now.getTime() - checkedAt;
    if (!Number.isFinite(checkedAt) || age < 0 || age >= exports.UPDATE_CHECK_TTL_MS) {
        return false;
    }
    try {
        parseSemVer(state.latest);
        return true;
    }
    catch {
        return false;
    }
}
async function fetchLatestVersion(channel, deps) {
    const fetchFn = deps.fetch ?? defaultFetch;
    const timeoutMs = deps.timeoutMs ?? exports.UPDATE_CHECK_TIMEOUT_MS;
    const controller = new AbortController();
    let timedOut = false;
    let timer;
    const timeout = new Promise((_resolve, reject) => {
        timer = setTimeout(() => {
            timedOut = true;
            controller.abort();
            reject(new Error(`Registry request timed out after ${timeoutMs}ms`));
        }, timeoutMs);
    });
    try {
        let response;
        try {
            response = await Promise.race([
                fetchFn(exports.NPM_REGISTRY_URL, { signal: controller.signal }),
                timeout,
            ]);
        }
        catch (error) {
            const message = timedOut
                ? `Registry request timed out after ${timeoutMs}ms`
                : errorMessage(error);
            throw new UpdateNetworkError(message);
        }
        if (!response.ok) {
            releaseFailedResponse(response, controller);
            throw new UpdateNetworkError(`npm registry returned HTTP ${response.status}`);
        }
        let metadata;
        try {
            metadata = await Promise.race([response.json(), timeout]);
        }
        catch (error) {
            if (timedOut) {
                throw new UpdateNetworkError(`Registry request timed out after ${timeoutMs}ms`);
            }
            if (error instanceof TypeError) {
                throw new UpdateNetworkError(errorMessage(error));
            }
            throw new UpdateMetadataError(`npm registry metadata is not valid JSON: ${errorMessage(error)}`);
        }
        if (!isRecord(metadata)) {
            throw new UpdateMetadataError("npm registry metadata must be a JSON object");
        }
        const distTags = metadata["dist-tags"];
        if (!isRecord(distTags)) {
            throw new UpdateMetadataError("npm registry metadata must contain dist-tags");
        }
        const version = distTags[channel];
        if (typeof version !== "string" || !version.trim()) {
            throw new UpdateMetadataError(`npm registry dist-tags.${channel} must be non-empty`);
        }
        try {
            parseSemVer(version);
        }
        catch (error) {
            throw new UpdateMetadataError(`npm registry dist-tags.${channel} is not valid SemVer: ${errorMessage(error)}`);
        }
        return version;
    }
    finally {
        if (timer !== undefined) {
            clearTimeout(timer);
        }
    }
}
function releaseFailedResponse(response, controller) {
    try {
        void response.body?.cancel().catch(() => undefined);
    }
    finally {
        controller.abort();
    }
}
function defaultFetch(input, init) {
    if (typeof globalThis.fetch !== "function") {
        return Promise.reject(new Error("global fetch is unavailable"));
    }
    return globalThis.fetch(input, init);
}
function isRecord(value) {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
