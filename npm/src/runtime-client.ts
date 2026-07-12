import type { ChildProcessWithoutNullStreams } from "node:child_process";
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";

import { kagentStatePath } from "./kagent-home";

import {
  parseRuntimeProtocolLine,
  type ApprovalResponseRequest,
  type CancelRequest,
  type ProviderConfigureRequest,
  type ProviderConfiguredEvent,
  type ProviderOption,
  type ProviderSnapshot,
  type RunRequest,
  type RuntimeReadyEvent,
  type RuntimeProtocolEvent,
  type RuntimeRequest,
  type SessionCommandRequest,
  type SteerRequest,
} from "./protocol";

type PythonRunner = {
  spawnPythonModule(
    moduleName: string,
    args?: string[],
    options?: { cwd?: string; env?: NodeJS.ProcessEnv },
  ): ChildProcessWithoutNullStreams;
};

const pythonRunner = require("./python-runner") as PythonRunner;
const PENDING_APPROVAL_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const PENDING_APPROVAL_FILE_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json$/i;
const APPROVAL_EXECUTION_INTERRUPTED_MESSAGE =
  "The approved action was interrupted and was not replayed because its side-effect state is uncertain.";

export type RuntimeClientEvent =
  | RuntimeProtocolEvent
  | { type: "client_stderr"; text: string }
  | { type: "client_failed"; message: string };

export type RuntimeSessionClient = {
  subscribe(handler: (event: RuntimeClientEvent) => void): () => void;
  configureProvider(
    config: ProviderConfiguration,
    onEvent: (event: RuntimeClientEvent) => void,
  ): void;
  run(
    goal: string,
    onEvent: (event: RuntimeClientEvent) => void,
    options?: { maxIterations?: number; runtimePlan?: string },
  ): void;
  command(command: string, onEvent: (event: RuntimeClientEvent) => void): void;
  respondToApproval(actionId: string, approved: boolean): void;
  steer(instruction: string): void;
  cancel(): void;
  close(): void;
};

export type ProviderConfiguration = {
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
};

export type RuntimeProviderState = {
  provider: ProviderSnapshot;
  options: ProviderOption[];
};

export function createRuntimeSessionClient(): RuntimeSessionClient {
  const sessionId = randomUUID();
  const configuredPendingApprovalPath = process.env.KAGENT_PENDING_APPROVAL_PATH;
  const pendingApprovalPath = configuredPendingApprovalPath || (() => {
    const pendingApprovalDirectory = kagentStatePath("pending-approvals");
    cleanupExpiredPendingApprovals(pendingApprovalDirectory);
    return path.join(pendingApprovalDirectory, `${sessionId}.json`);
  })();
  let child: ChildProcessWithoutNullStreams | null = null;
  let stdout: readline.Interface | null = null;
  let currentHandler: ((event: RuntimeClientEvent) => void) | null = null;
  let busy = false;
  let closed = false;
  let generation = 0;
  let ready = false;
  let restartUsed = false;
  let queuedRequest: RuntimeRequest | null = null;
  let startupFailure = "";
  let approvalExecutionUncertain = false;
  let recoveringActive = false;
  let recoveryFailureMessage = "";
  let lifecycleEvent: RuntimeReadyEvent | null = null;
  const subscribers = new Set<(event: RuntimeClientEvent) => void>();

  function spawn(): void {
    generation += 1;
    const childGeneration = generation;
    ready = false;
    let nextChild: ChildProcessWithoutNullStreams;
    try {
      nextChild = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", [], {
        cwd: process.cwd(),
        env: {
          ...process.env,
          KAGENT_PENDING_APPROVAL_PATH: pendingApprovalPath,
        },
      });
    } catch (error) {
      recoverFromChildFailure(childGeneration, errorMessage(error));
      return;
    }
    const nextStdout = readline.createInterface({ input: nextChild.stdout });
    child = nextChild;
    stdout = nextStdout;

    nextStdout.on("line", (line) => {
      if (childGeneration !== generation) {
        return;
      }
      try {
        const event = parseRuntimeProtocolLine(line);
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
            } else if (event.approval_execution_interrupted) {
              approvalExecutionUncertain = true;
              recoveringActive = false;
              recoveryFailureMessage = "";
              queuedRequest = null;
            } else {
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
        if (
          event.type === "run_completed" ||
          event.type === "run_failed" ||
          event.type === "provider_configured" ||
          event.type === "provider_configuration_failed" ||
          event.type === "session_command_completed" ||
          event.type === "session_command_failed"
        ) {
          if (event.type === "run_completed" || event.type === "run_failed") {
            cleanupPendingApproval();
          }
          approvalExecutionUncertain = false;
          recoveringActive = false;
          recoveryFailureMessage = "";
          busy = false;
          currentHandler = null;
        }
      } catch (error) {
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
      recoverFromChildFailure(
        childGeneration,
        `runtime exited with code ${code ?? 1}`,
      );
    });
  }

  function recoverFromChildFailure(childGeneration: number, message: string): void {
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
        } else {
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
    } else if (busy) {
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

  function writeNow(request: RuntimeRequest): void {
    if (
      !child ||
      child.killed ||
      child.exitCode !== null ||
      child.signalCode !== null ||
      !child.stdin.writable
    ) {
      throw new Error("runtime session is not available");
    }
    child.stdin.write(`${JSON.stringify(request)}\n`);
  }

  function send(request: RuntimeRequest): void {
    if (startupFailure) {
      throw new Error(startupFailure);
    }
    if (!ready) {
      queuedRequest = request;
      return;
    }
    writeNow(request);
  }

  function notify(event: RuntimeClientEvent): void {
    for (const subscriber of subscribers) {
      subscriber(event);
    }
  }

  function updateProviderLifecycle(event: ProviderConfiguredEvent): void {
    if (!lifecycleEvent) {
      return;
    }
    lifecycleEvent = { ...lifecycleEvent, provider: event.provider };
    notify(lifecycleEvent);
  }

  function failCurrent(message: string): void {
    failCurrentWithEvent({ type: "client_failed", message });
  }

  function failCurrentWithEvent(event: RuntimeClientEvent): void {
    const handler = currentHandler;
    const preserveUncertainTombstone =
      event.type === "run_failed" &&
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
      } else if (startupFailure) {
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
      const request: ProviderConfigureRequest = {
        type: "provider_configure",
        provider: config.provider,
        base_url: config.baseUrl,
        model: config.model,
        api_key: config.apiKey,
      };
      try {
        send(request);
      } catch (error) {
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
      const request: RunRequest = {
        type: "run_request",
        goal,
        max_iterations: options.maxIterations ?? 3,
      };
      if (options.runtimePlan) {
        request.runtime_plan = options.runtimePlan;
      }
      try {
        send(request);
      } catch (error) {
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
      const request: SessionCommandRequest = {
        type: "session_command",
        command,
      };
      try {
        send(request);
      } catch (error) {
        failCurrent(errorMessage(error));
      }
    },
    respondToApproval(actionId, approved) {
      if (!busy || !currentHandler) {
        throw new Error("there is no pending runtime request");
      }
      const request: ApprovalResponseRequest = {
        type: "approval_response",
        action_id: actionId,
        approved,
      };
      approvalExecutionUncertain = approved;
      try {
        send(request);
      } catch (error) {
        queuedRequest = request;
        child?.kill();
        recoverFromChildFailure(generation, errorMessage(error));
      }
    },
    steer(instruction) {
      if (!busy || !currentHandler) {
        throw new Error("there is no active runtime request to steer");
      }
      const request: SteerRequest = {
        type: "steer_request",
        instruction,
      };
      try {
        send(request);
      } catch (error) {
        failCurrent(errorMessage(error));
      }
    },
    cancel() {
      if (!busy) {
        return;
      }
      const request: CancelRequest = {
        type: "cancel_request",
        reason: "user requested cancellation",
      };
      try {
        send(request);
      } catch (error) {
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

  function cleanupPendingApproval(): void {
    try {
      fs.unlinkSync(pendingApprovalPath);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
        // The Python runtime still owns validation and persistence errors.
      }
    }
  }
}

function cleanupExpiredPendingApprovals(directory: string): void {
  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch {
    return;
  }
  const cutoff = Date.now() - PENDING_APPROVAL_MAX_AGE_MS;
  for (const entry of entries) {
    if (!entry.isFile() || !PENDING_APPROVAL_FILE_PATTERN.test(entry.name)) {
      continue;
    }
    const candidate = path.join(directory, entry.name);
    try {
      const stats = fs.lstatSync(candidate);
      if (stats.isFile() && stats.mtimeMs < cutoff) {
        fs.unlinkSync(candidate);
      }
    } catch {
      // A concurrent runtime may have replaced or removed the snapshot.
    }
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
