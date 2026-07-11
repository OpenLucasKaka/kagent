"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.createRuntimeSessionClient = createRuntimeSessionClient;
const node_crypto_1 = require("node:crypto");
const node_fs_1 = __importDefault(require("node:fs"));
const node_os_1 = __importDefault(require("node:os"));
const node_path_1 = __importDefault(require("node:path"));
const node_readline_1 = __importDefault(require("node:readline"));
const protocol_1 = require("./protocol");
const pythonRunner = require("./python-runner");
const PENDING_APPROVAL_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const PENDING_APPROVAL_FILE_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$/i;
const APPROVAL_EXECUTION_INTERRUPTED_MESSAGE = "The approved action was interrupted and was not replayed because its side-effect state is uncertain.";
function createRuntimeSessionClient() {
    const sessionId = (0, node_crypto_1.randomUUID)();
    const stateHome = process.env.XDG_STATE_HOME || node_path_1.default.join(node_os_1.default.homedir(), ".local", "state");
    const configuredPendingApprovalPath = process.env.KAGENT_PENDING_APPROVAL_PATH;
    const pendingApprovalDirectory = node_path_1.default.join(stateHome, "kagent", "pending-approvals");
    if (!configuredPendingApprovalPath) {
        cleanupExpiredPendingApprovals(pendingApprovalDirectory);
    }
    const pendingApprovalPath = configuredPendingApprovalPath || node_path_1.default.join(pendingApprovalDirectory, `${sessionId}.json`);
    let child = null;
    let stdout = null;
    let currentHandler = null;
    let busy = false;
    let closed = false;
    let generation = 0;
    let ready = false;
    let restartUsed = false;
    let queuedRequest = null;
    let startupFailure = "";
    let approvalExecutionUncertain = false;
    let recoveringActive = false;
    let recoveryFailureMessage = "";
    let lifecycleEvent = null;
    const subscribers = new Set();
    function spawn() {
        generation += 1;
        const childGeneration = generation;
        ready = false;
        let nextChild;
        try {
            nextChild = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", [], {
                cwd: process.cwd(),
                env: {
                    ...process.env,
                    KAGENT_PENDING_APPROVAL_PATH: pendingApprovalPath,
                },
            });
        }
        catch (error) {
            recoverFromChildFailure(childGeneration, errorMessage(error));
            return;
        }
        const nextStdout = node_readline_1.default.createInterface({ input: nextChild.stdout });
        child = nextChild;
        stdout = nextStdout;
        nextStdout.on("line", (line) => {
            if (childGeneration !== generation) {
                return;
            }
            try {
                const event = (0, protocol_1.parseRuntimeProtocolLine)(line);
                if (!event) {
                    return;
                }
                if (event.type === "runtime_ready") {
                    ready = true;
                    startupFailure = "";
                    lifecycleEvent = event;
                    notify(event);
                    if (recoveringActive) {
                        if (event.pending_approval) {
                            approvalExecutionUncertain = false;
                            recoveringActive = false;
                            recoveryFailureMessage = "";
                        }
                        else if (event.approval_execution_interrupted) {
                            approvalExecutionUncertain = true;
                            recoveringActive = false;
                            recoveryFailureMessage = "";
                            queuedRequest = null;
                        }
                        else {
                            const failureMessage = recoveryFailureMessage;
                            recoveringActive = false;
                            recoveryFailureMessage = "";
                            failCurrent(failureMessage);
                        }
                    }
                    if (queuedRequest) {
                        const request = queuedRequest;
                        queuedRequest = null;
                        writeNow(request);
                    }
                    return;
                }
                if (event.type === "runtime_unavailable") {
                    ready = false;
                    startupFailure = event.message;
                    notify(event);
                    failCurrent(event.message);
                    return;
                }
                if (!currentHandler) {
                    return;
                }
                if (event.type === "approval_required") {
                    approvalExecutionUncertain = false;
                }
                currentHandler(event);
                if (event.type === "provider_configured") {
                    updateProviderLifecycle(event);
                }
                if (event.type === "run_completed" ||
                    event.type === "run_failed" ||
                    event.type === "provider_configured" ||
                    event.type === "provider_configuration_failed" ||
                    event.type === "session_command_completed" ||
                    event.type === "session_command_failed") {
                    if (event.type === "run_completed" || event.type === "run_failed") {
                        cleanupPendingApproval();
                    }
                    approvalExecutionUncertain = false;
                    recoveringActive = false;
                    recoveryFailureMessage = "";
                    busy = false;
                    currentHandler = null;
                }
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        });
        nextChild.stderr.on("data", () => {
            // Drain the child pipe, but never forward stderr into user-visible events.
        });
        nextChild.on("error", (error) => {
            recoverFromChildFailure(childGeneration, error.message);
        });
        nextChild.on("close", (code) => {
            recoverFromChildFailure(childGeneration, `runtime exited with code ${code ?? 1}`);
        });
    }
    function recoverFromChildFailure(childGeneration, message) {
        if (childGeneration !== generation || closed) {
            return;
        }
        generation += 1;
        ready = false;
        lifecycleEvent = null;
        stdout?.close();
        child = null;
        stdout = null;
        const activeRequest = busy && currentHandler !== null;
        if (restartUsed) {
            const preserveUncertainTombstone = approvalExecutionUncertain;
            if (activeRequest) {
                if (preserveUncertainTombstone) {
                    failCurrentWithEvent({
                        type: "run_failed",
                        error_code: "approval_execution_interrupted",
                        message: APPROVAL_EXECUTION_INTERRUPTED_MESSAGE,
                    });
                }
                else {
                    failCurrent(message);
                }
            }
            if (!preserveUncertainTombstone) {
                cleanupPendingApproval();
            }
            startupFailure = message;
            notify({ type: "client_failed", message });
            return;
        }
        if (activeRequest) {
            recoveringActive = true;
            recoveryFailureMessage = message;
        }
        else if (busy) {
            failCurrent(message);
        }
        restartUsed = true;
        startupFailure = "";
        setImmediate(() => {
            if (!closed) {
                spawn();
            }
        });
    }
    function writeNow(request) {
        if (!child ||
            child.killed ||
            child.exitCode !== null ||
            child.signalCode !== null ||
            !child.stdin.writable) {
            throw new Error("runtime session is not available");
        }
        child.stdin.write(`${JSON.stringify(request)}\n`);
    }
    function send(request) {
        if (startupFailure) {
            throw new Error(startupFailure);
        }
        if (!ready) {
            queuedRequest = request;
            return;
        }
        writeNow(request);
    }
    function notify(event) {
        for (const subscriber of subscribers) {
            subscriber(event);
        }
    }
    function updateProviderLifecycle(event) {
        if (!lifecycleEvent) {
            return;
        }
        lifecycleEvent = { ...lifecycleEvent, provider: event.provider };
        notify(lifecycleEvent);
    }
    function failCurrent(message) {
        failCurrentWithEvent({ type: "client_failed", message });
    }
    function failCurrentWithEvent(event) {
        const handler = currentHandler;
        const preserveUncertainTombstone = event.type === "run_failed" &&
            event.error_code === "approval_execution_interrupted";
        busy = false;
        currentHandler = null;
        queuedRequest = null;
        approvalExecutionUncertain = preserveUncertainTombstone;
        recoveringActive = false;
        recoveryFailureMessage = "";
        handler?.(event);
    }
    spawn();
    return {
        subscribe(handler) {
            subscribers.add(handler);
            if (lifecycleEvent) {
                handler(lifecycleEvent);
            }
            else if (startupFailure) {
                handler({ type: "client_failed", message: startupFailure });
            }
            return () => subscribers.delete(handler);
        },
        configureProvider(config, onEvent) {
            if (closed) {
                onEvent({ type: "client_failed", message: "runtime session is closed" });
                return;
            }
            if (busy) {
                onEvent({ type: "client_failed", message: "runtime session is busy" });
                return;
            }
            busy = true;
            currentHandler = onEvent;
            const request = {
                type: "provider_configure",
                provider: config.provider,
                base_url: config.baseUrl,
                model: config.model,
                api_key: config.apiKey,
            };
            try {
                send(request);
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        },
        run(goal, onEvent, options = {}) {
            if (closed) {
                onEvent({ type: "client_failed", message: "runtime session is closed" });
                return;
            }
            if (busy) {
                onEvent({ type: "client_failed", message: "runtime session is busy" });
                return;
            }
            busy = true;
            currentHandler = onEvent;
            const request = {
                type: "run_request",
                goal,
                max_iterations: options.maxIterations ?? 3,
            };
            if (options.runtimePlan) {
                request.runtime_plan = options.runtimePlan;
            }
            try {
                send(request);
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        },
        command(command, onEvent) {
            if (closed) {
                onEvent({ type: "client_failed", message: "runtime session is closed" });
                return;
            }
            if (busy) {
                onEvent({ type: "client_failed", message: "runtime session is busy" });
                return;
            }
            busy = true;
            currentHandler = onEvent;
            const request = {
                type: "session_command",
                command,
            };
            try {
                send(request);
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        },
        respondToApproval(actionId, approved) {
            if (!busy || !currentHandler) {
                throw new Error("there is no pending runtime request");
            }
            const request = {
                type: "approval_response",
                action_id: actionId,
                approved,
            };
            approvalExecutionUncertain = approved;
            try {
                send(request);
            }
            catch (error) {
                queuedRequest = request;
                child?.kill();
                recoverFromChildFailure(generation, errorMessage(error));
            }
        },
        steer(instruction) {
            if (!busy || !currentHandler) {
                throw new Error("there is no active runtime request to steer");
            }
            const request = {
                type: "steer_request",
                instruction,
            };
            try {
                send(request);
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        },
        cancel() {
            if (!busy) {
                return;
            }
            const request = {
                type: "cancel_request",
                reason: "user requested cancellation",
            };
            try {
                send(request);
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        },
        close() {
            if (closed) {
                return;
            }
            closed = true;
            const preserveUncertainTombstone = approvalExecutionUncertain;
            busy = false;
            currentHandler = null;
            queuedRequest = null;
            approvalExecutionUncertain = false;
            recoveringActive = false;
            recoveryFailureMessage = "";
            subscribers.clear();
            generation += 1;
            stdout?.close();
            if (child && !child.killed) {
                child.kill("SIGTERM");
            }
            child = null;
            stdout = null;
            if (!preserveUncertainTombstone) {
                cleanupPendingApproval();
            }
        },
    };
    function cleanupPendingApproval() {
        try {
            node_fs_1.default.unlinkSync(pendingApprovalPath);
        }
        catch (error) {
            if (error.code !== "ENOENT") {
                // The Python runtime still owns validation and persistence errors.
            }
        }
    }
}
function cleanupExpiredPendingApprovals(directory) {
    let entries;
    try {
        entries = node_fs_1.default.readdirSync(directory, { withFileTypes: true });
    }
    catch {
        return;
    }
    const cutoff = Date.now() - PENDING_APPROVAL_MAX_AGE_MS;
    for (const entry of entries) {
        if (!entry.isFile() || !PENDING_APPROVAL_FILE_PATTERN.test(entry.name)) {
            continue;
        }
        const candidate = node_path_1.default.join(directory, entry.name);
        try {
            const stats = node_fs_1.default.lstatSync(candidate);
            if (stats.isFile() && stats.mtimeMs < cutoff) {
                node_fs_1.default.unlinkSync(candidate);
            }
        }
        catch {
            // A concurrent runtime may have replaced or removed the snapshot.
        }
    }
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
