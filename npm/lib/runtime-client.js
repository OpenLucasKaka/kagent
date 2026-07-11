"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.createRuntimeSessionClient = createRuntimeSessionClient;
const node_readline_1 = __importDefault(require("node:readline"));
const protocol_1 = require("./protocol");
const pythonRunner = require("./python-runner");
function createRuntimeSessionClient() {
    let child = null;
    let stdout = null;
    let currentHandler = null;
    let busy = false;
    let closed = false;
    let generation = 0;
    let ready = false;
    let queuedRequest = null;
    let startupFailure = "";
    let lastStderrLine = "";
    let lifecycleEvent = null;
    const subscribers = new Set();
    function spawn() {
        generation += 1;
        const childGeneration = generation;
        const nextChild = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", []);
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
                    busy = false;
                    currentHandler = null;
                }
            }
            catch (error) {
                failCurrent(errorMessage(error));
            }
        });
        nextChild.stderr.on("data", (chunk) => {
            const text = chunk.toString("utf8");
            lastStderrLine = lastNonEmptyLine(text) || lastStderrLine;
            currentHandler?.({ type: "client_stderr", text });
        });
        nextChild.on("error", (error) => {
            if (childGeneration === generation) {
                failCurrent(error.message);
            }
        });
        nextChild.on("close", (code) => {
            if (childGeneration !== generation || closed) {
                return;
            }
            if (busy) {
                failCurrent(lastStderrLine || `runtime exited with code ${code ?? 1}`);
            }
            else {
                ready = false;
                startupFailure = lastStderrLine || `runtime exited with code ${code ?? 1}`;
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
        const handler = currentHandler;
        busy = false;
        currentHandler = null;
        queuedRequest = null;
        handler?.({ type: "client_failed", message });
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
            busy = false;
            currentHandler = null;
            queuedRequest = null;
            subscribers.clear();
            generation += 1;
            stdout?.close();
            if (child && !child.killed) {
                child.kill("SIGTERM");
            }
            child = null;
            stdout = null;
        },
    };
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
function lastNonEmptyLine(text) {
    const lines = text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);
    return lines.at(-1) ?? "";
}
