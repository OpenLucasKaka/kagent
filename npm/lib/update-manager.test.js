"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const update_manager_1 = require("./update-manager");
function registryResponse(version, tag = "latest") {
    return {
        ok: true,
        status: 200,
        async json() {
            return { "dist-tags": { [tag]: version } };
        },
    };
}
function assertErrorSkip(result, reason, error) {
    strict_1.default.ok(result && typeof result === "object");
    const record = result;
    strict_1.default.equal(record.skipped, true);
    strict_1.default.equal(record.reason, reason);
    strict_1.default.equal(record.latest, null);
    strict_1.default.equal(record.updateAvailable, false);
    strict_1.default.match(String(record.error), error);
}
(0, node_test_1.default)("maps stable/latest and beta/next update channel configuration", () => {
    strict_1.default.equal(update_manager_1.UPDATE_CHECK_TIMEOUT_MS, 3_000);
    strict_1.default.equal(update_manager_1.UPDATE_CHECK_TTL_MS, 24 * 60 * 60 * 1_000);
    strict_1.default.equal((0, update_manager_1.resolveUpdateChannel)({}), "latest");
    strict_1.default.equal((0, update_manager_1.resolveUpdateChannel)({ KAGENT_UPDATE_CHANNEL: "stable" }), "latest");
    strict_1.default.equal((0, update_manager_1.resolveUpdateChannel)({ KAGENT_UPDATE_CHANNEL: "latest" }), "latest");
    strict_1.default.equal((0, update_manager_1.resolveUpdateChannel)({ KAGENT_UPDATE_CHANNEL: "beta" }), "next");
    strict_1.default.equal((0, update_manager_1.resolveUpdateChannel)({ KAGENT_UPDATE_CHANNEL: "next" }), "next");
    strict_1.default.throws(() => (0, update_manager_1.resolveUpdateChannel)({ KAGENT_UPDATE_CHANNEL: "nightly" }), /KAGENT_UPDATE_CHANNEL.*nightly.*stable.*beta/i);
});
(0, node_test_1.default)("compares valid SemVer including prerelease identifiers", () => {
    strict_1.default.equal((0, update_manager_1.compareSemVer)("1.10.0", "1.9.9"), 1);
    strict_1.default.equal((0, update_manager_1.compareSemVer)("2.0.0", "10.0.0"), -1);
    strict_1.default.equal((0, update_manager_1.compareSemVer)("1.0.0", "1.0.0-beta.99"), 1);
    strict_1.default.equal((0, update_manager_1.compareSemVer)("1.0.0-beta.11", "1.0.0-beta.2"), 1);
    strict_1.default.equal((0, update_manager_1.compareSemVer)("1.0.0-beta.2", "1.0.0-beta.alpha"), -1);
    strict_1.default.equal((0, update_manager_1.compareSemVer)("1.0.0+build.1", "1.0.0+build.2"), 0);
});
(0, node_test_1.default)("rejects invalid SemVer", () => {
    for (const version of ["1.2", "v1.2.3", "01.2.3", "1.2.3-01", "1.2.x", ""]) {
        strict_1.default.throws(() => (0, update_manager_1.compareSemVer)(version, "1.0.0"), /invalid semver/i);
    }
});
(0, node_test_1.default)("fetches the fixed registry URL and selected dist-tag", async () => {
    const calls = [];
    const result = await (0, update_manager_1.checkForUpdate)({
        currentVersion: "1.2.3",
        channel: "next",
        force: true,
        deps: {
            now: () => new Date("2026-07-13T00:00:00.000Z"),
            fetch: async (url, init) => {
                calls.push({ url: String(url), signal: init?.signal ?? undefined });
                return registryResponse("1.3.0-beta.1", "next");
            },
        },
    });
    strict_1.default.deepEqual(calls.map((call) => call.url), [update_manager_1.NPM_REGISTRY_URL]);
    strict_1.default.equal(calls[0]?.signal instanceof AbortSignal, true);
    strict_1.default.deepEqual(result, {
        current: "1.2.3",
        latest: "1.3.0-beta.1",
        channel: "next",
        updateAvailable: true,
        checkedAt: "2026-07-13T00:00:00.000Z",
    });
});
(0, node_test_1.default)("uses a fresh same-channel state without a network request", async () => {
    let fetchCalls = 0;
    const state = {
        channel: "latest",
        latest: "1.4.0",
        checkedAt: "2026-07-12T12:00:01.000Z",
    };
    const result = await (0, update_manager_1.checkForUpdate)({
        currentVersion: "1.3.0",
        deps: {
            now: () => new Date("2026-07-13T12:00:00.000Z"),
            readState: async () => state,
            fetch: async () => {
                fetchCalls += 1;
                return registryResponse("9.0.0");
            },
        },
    });
    strict_1.default.equal(fetchCalls, 0);
    strict_1.default.deepEqual(result, {
        current: "1.3.0",
        latest: "1.4.0",
        channel: "latest",
        updateAvailable: true,
        checkedAt: state.checkedAt,
        skipped: true,
        reason: "ttl",
    });
});
(0, node_test_1.default)("force ignores TTL and persists a successful check", async () => {
    const writes = [];
    const result = await (0, update_manager_1.checkForUpdate)({
        currentVersion: "1.3.0",
        force: true,
        deps: {
            now: () => new Date("2026-07-13T12:00:00.000Z"),
            readState: async () => ({
                channel: "latest",
                latest: "1.4.0",
                checkedAt: "2026-07-13T11:59:59.000Z",
            }),
            writeState: async (state) => {
                writes.push(state);
            },
            fetch: async () => registryResponse("1.5.0"),
        },
    });
    strict_1.default.equal(result.latest, "1.5.0");
    strict_1.default.deepEqual(writes, [{
            channel: "latest",
            latest: "1.5.0",
            checkedAt: "2026-07-13T12:00:00.000Z",
        }]);
});
(0, node_test_1.default)("skips malformed metadata automatically and rejects it when forced", async () => {
    const malformed = [
        null,
        [],
        {},
        { "dist-tags": null },
        { "dist-tags": { latest: "" } },
        { "dist-tags": { latest: "not-a-version" } },
    ];
    const readers = [
        async () => { throw new SyntaxError("Unexpected end of JSON input"); },
        ...malformed.map((payload) => async () => payload),
    ];
    for (const json of readers) {
        const deps = {
            now: () => new Date("2026-07-13T00:00:00.000Z"),
            fetch: async () => ({ ok: true, status: 200, json }),
        };
        const automatic = await (0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", deps });
        assertErrorSkip(automatic, "metadata-error", /json|metadata|dist-tags|semver/i);
        await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({
            currentVersion: "1.0.0",
            force: true,
            deps,
        }), /registry metadata|dist-tags|semver/i);
    }
});
(0, node_test_1.default)("returns a skipped result on automatic network errors and throws when forced", async () => {
    const deps = {
        now: () => new Date("2026-07-13T00:00:00.000Z"),
        fetch: async () => { throw new Error("socket closed"); },
    };
    strict_1.default.deepEqual(await (0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", deps }), {
        current: "1.0.0",
        latest: null,
        channel: "latest",
        updateAvailable: false,
        checkedAt: "2026-07-13T00:00:00.000Z",
        skipped: true,
        reason: "network-error",
        error: "socket closed",
    });
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", force: true, deps }), /unable to check.*socket closed/i);
});
(0, node_test_1.default)("releases non-2xx response bodies and aborts the request", async () => {
    const originalFetch = globalThis.fetch;
    let bodyCancellations = 0;
    const requestSignals = [];
    globalThis.fetch = (async (url, init) => {
        strict_1.default.equal(String(url), update_manager_1.NPM_REGISTRY_URL);
        if (init?.signal) {
            requestSignals.push(init.signal);
        }
        return {
            ok: false,
            status: 503,
            body: {
                async cancel() { bodyCancellations += 1; },
            },
            json: () => new Promise(() => undefined),
        };
    });
    try {
        const deps = {
            now: () => new Date("2026-07-13T00:00:00.000Z"),
        };
        const result = await (0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", deps });
        assertErrorSkip(result, "network-error", /HTTP 503/i);
        await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", force: true, deps }), /unable to check.*HTTP 503/i);
    }
    finally {
        globalThis.fetch = originalFetch;
    }
    strict_1.default.equal(bodyCancellations, 2);
    strict_1.default.equal(requestSignals.length, 2);
    strict_1.default.equal(requestSignals.every((signal) => signal.aborted), true);
});
(0, node_test_1.default)("treats cache failures as automatic warnings but keeps forced writes strict", async () => {
    const now = () => new Date("2026-07-13T00:00:00.000Z");
    let fetches = 0;
    const readFailure = await (0, update_manager_1.checkForUpdate)({
        currentVersion: "1.0.0",
        deps: {
            now,
            readState: async () => { throw new Error("EACCES"); },
            fetch: async () => {
                fetches += 1;
                return registryResponse("2.0.0");
            },
        },
    });
    strict_1.default.equal(fetches, 1);
    strict_1.default.deepEqual(readFailure, {
        current: "1.0.0",
        latest: "2.0.0",
        channel: "latest",
        updateAvailable: true,
        checkedAt: "2026-07-13T00:00:00.000Z",
        cacheWarning: "Unable to read update cache: EACCES",
    });
    const writeDeps = {
        now,
        fetch: async () => registryResponse("2.0.0"),
        writeState: async () => { throw new Error("ENOSPC"); },
    };
    const writeFailure = await (0, update_manager_1.checkForUpdate)({
        currentVersion: "1.0.0",
        deps: writeDeps,
    });
    strict_1.default.deepEqual(writeFailure, {
        current: "1.0.0",
        latest: "2.0.0",
        channel: "latest",
        updateAvailable: true,
        checkedAt: "2026-07-13T00:00:00.000Z",
        cacheWarning: "Unable to write update cache: ENOSPC",
    });
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", force: true, deps: writeDeps }), /ENOSPC/);
});
(0, node_test_1.default)("treats metadata body network failures as skippable", async () => {
    const deps = {
        now: () => new Date("2026-07-13T00:00:00.000Z"),
        fetch: async () => ({
            ok: true,
            status: 200,
            async json() { throw new TypeError("terminated"); },
        }),
    };
    strict_1.default.deepEqual(await (0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", deps }), {
        current: "1.0.0",
        latest: null,
        channel: "latest",
        updateAvailable: false,
        checkedAt: "2026-07-13T00:00:00.000Z",
        skipped: true,
        reason: "network-error",
        error: "terminated",
    });
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", force: true, deps }), /unable to check.*terminated/i);
});
(0, node_test_1.default)("aborts registry requests after the configured timeout", async () => {
    const deps = {
        now: () => new Date("2026-07-13T00:00:00.000Z"),
        timeoutMs: 5,
        fetch: (_url, init) => new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new Error("aborted")));
        }),
    };
    const automatic = await (0, update_manager_1.checkForUpdate)({ currentVersion: "1.0.0", deps });
    assertErrorSkip(automatic, "network-error", /timed out.*5ms/i);
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({
        currentVersion: "1.0.0",
        force: true,
        deps,
    }), /unable to check.*timed out.*5ms/i);
});
(0, node_test_1.default)("rejects local version and channel errors before requesting metadata", async () => {
    let fetches = 0;
    const deps = {
        fetch: async () => {
            fetches += 1;
            return registryResponse("2.0.0");
        },
    };
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({ currentVersion: "v1.0.0", deps }), /invalid semver/i);
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({
        currentVersion: "1.0.0",
        channel: "nightly",
        deps,
    }), /update channel.*nightly.*latest.*next/i);
    strict_1.default.equal(fetches, 0);
});
(0, node_test_1.default)("keeps the registry timeout active while reading metadata", async () => {
    await strict_1.default.rejects((0, update_manager_1.checkForUpdate)({
        currentVersion: "1.0.0",
        force: true,
        deps: {
            timeoutMs: 5,
            fetch: async () => ({
                ok: true,
                status: 200,
                json: () => new Promise((_resolve, reject) => {
                    setTimeout(() => reject(new Error("body stalled")), 20);
                }),
            }),
        },
    }), /unable to check.*timed out.*5ms/i);
});
(0, node_test_1.default)("upgrades using fixed npm argv for each channel", async () => {
    for (const [channel, expectedSpec, latest] of [
        ["latest", "@openlucaskaka/kagent@latest", "2.0.0"],
        ["next", "@openlucaskaka/kagent@next", "2.1.0-beta.1"],
    ]) {
        const installs = [];
        const result = await (0, update_manager_1.runUpgrade)({
            currentVersion: "1.0.0",
            channel,
            deps: {
                readState: async () => {
                    throw new Error("runUpgrade must force the update check");
                },
                fetch: async () => registryResponse(latest, channel),
                runInstall: async (argv) => { installs.push(argv); },
                readInstalledVersion: async () => latest,
            },
        });
        strict_1.default.deepEqual(installs, [["install", "--global", expectedSpec]]);
        strict_1.default.equal(result.latest, latest);
    }
});
(0, node_test_1.default)("does not install when current is latest and validates the installed version", async () => {
    let installs = 0;
    const noUpdate = await (0, update_manager_1.runUpgrade)({
        currentVersion: "2.0.0",
        deps: {
            fetch: async () => registryResponse("2.0.0"),
            runInstall: async () => { installs += 1; },
            readInstalledVersion: async () => "2.0.0",
        },
    });
    strict_1.default.equal(installs, 0);
    strict_1.default.equal(noUpdate.updateAvailable, false);
    await strict_1.default.rejects((0, update_manager_1.runUpgrade)({
        currentVersion: "1.0.0",
        deps: {
            fetch: async () => registryResponse("2.0.0"),
            runInstall: async () => undefined,
            readInstalledVersion: async () => "1.9.9",
        },
    }), /installed version 1\.9\.9.*expected.*2\.0\.0/i);
});
(0, node_test_1.default)("reports the fixed target when installation fails", async () => {
    await strict_1.default.rejects((0, update_manager_1.runUpgrade)({
        currentVersion: "1.0.0",
        deps: {
            fetch: async () => registryResponse("2.0.0"),
            runInstall: async () => { throw new Error("permission denied"); },
            readInstalledVersion: async () => "1.0.0",
        },
    }), /failed to install @openlucaskaka\/kagent@latest: permission denied/i);
});
(0, node_test_1.default)("runUpgrade keeps forced update-check failures strict", async () => {
    await strict_1.default.rejects((0, update_manager_1.runUpgrade)({
        currentVersion: "1.0.0",
        deps: {
            fetch: async () => ({
                ok: true,
                status: 200,
                async json() { return { "dist-tags": { latest: "invalid" } }; },
            }),
            runInstall: async () => undefined,
            readInstalledVersion: async () => "1.0.0",
        },
    }), /registry metadata|semver/i);
});
