import type { ChildProcessWithoutNullStreams } from "node:child_process";
import readline from "node:readline";

import {
  parseRuntimeProtocolLine,
  type ApprovalResponseRequest,
  type RunRequest,
  type RuntimeProtocolEvent,
  type RuntimeRequest,
} from "./protocol";

type PythonRunner = {
  spawnPythonModule(moduleName: string, args?: string[]): ChildProcessWithoutNullStreams;
};

const pythonRunner = require("./python-runner") as PythonRunner;

export type RuntimeClientEvent =
  | RuntimeProtocolEvent
  | { type: "client_stderr"; text: string }
  | { type: "client_failed"; message: string };

export type RuntimeSessionClient = {
  run(
    goal: string,
    onEvent: (event: RuntimeClientEvent) => void,
    options?: { maxIterations?: number; runtimePlan?: string },
  ): void;
  respondToApproval(actionId: string, approved: boolean): void;
  cancel(): void;
  close(): void;
};

export function createRuntimeSessionClient(): RuntimeSessionClient {
  let child: ChildProcessWithoutNullStreams | null = null;
  let stdout: readline.Interface | null = null;
  let currentHandler: ((event: RuntimeClientEvent) => void) | null = null;
  let busy = false;
  let closed = false;
  let generation = 0;
  let ready = false;
  let queuedRequest: RuntimeRequest | null = null;
  let startupFailure = "";
  let lastStderrLine = "";

  function spawn(): void {
    generation += 1;
    const childGeneration = generation;
    const nextChild = pythonRunner.spawnPythonModule("kagent.cli.stdio_runtime", []);
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
          failCurrent(event.message);
          return;
        }
        if (!currentHandler) {
          return;
        }
        currentHandler(event);
        if (event.type === "run_completed" || event.type === "run_failed") {
          busy = false;
          currentHandler = null;
        }
      } catch (error) {
        failCurrent(errorMessage(error));
      }
    });
    nextChild.stderr.on("data", (chunk: Buffer) => {
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
      } else {
        ready = false;
        startupFailure = lastStderrLine || `runtime exited with code ${code ?? 1}`;
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

  function failCurrent(message: string): void {
    const handler = currentHandler;
    busy = false;
    currentHandler = null;
    queuedRequest = null;
    handler?.({ type: "client_failed", message });
  }

  function restart(): void {
    generation += 1;
    stdout?.close();
    if (child && !child.killed) {
      child.kill("SIGTERM");
    }
    child = null;
    stdout = null;
    ready = false;
    queuedRequest = null;
    startupFailure = "";
    lastStderrLine = "";
    if (!closed) {
      spawn();
    }
  }

  spawn();

  return {
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
    respondToApproval(actionId, approved) {
      if (!busy || !currentHandler) {
        throw new Error("there is no pending runtime request");
      }
      const request: ApprovalResponseRequest = {
        type: "approval_response",
        action_id: actionId,
        approved,
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
      busy = false;
      currentHandler = null;
      restart();
    },
    close() {
      if (closed) {
        return;
      }
      closed = true;
      busy = false;
      currentHandler = null;
      queuedRequest = null;
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function lastNonEmptyLine(text: string): string {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  return lines.at(-1) ?? "";
}
