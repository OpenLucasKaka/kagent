import {
  KagentInkApp,
  type TerminalCursorController,
} from "./App";
import type { PromptTerminalCursorControl } from "./ui-components";

type FallbackOptions = {
  fallback?: () => void;
};

type DynamicImport = (specifier: string) => Promise<unknown>;

const dynamicImport = new Function("specifier", "return import(specifier)") as DynamicImport;

export function createCursorSynchronizedStdout(
  target: NodeJS.WriteStream,
): {
  cursor: TerminalCursorController;
  stdout: NodeJS.WriteStream;
} {
  let desiredControl: PromptTerminalCursorControl | null = null;
  let positionedControl: PromptTerminalCursorControl | null = null;
  const cursor: TerminalCursorController = {
    update(control) {
      desiredControl = control;
    },
  };
  const stdout = new Proxy(target, {
    get(stream, property) {
      if (property === "write") {
        return (...args: unknown[]): boolean => {
          if (positionedControl) {
            stream.write(positionedControl.restore);
            positionedControl = null;
          }
          const result = Reflect.apply(stream.write, stream, args) as boolean;
          if (desiredControl) {
            stream.write(desiredControl.position);
            positionedControl = desiredControl;
          }
          return result;
        };
      }
      const value = Reflect.get(stream, property, stream) as unknown;
      return typeof value === "function"
        ? (value as (...args: unknown[]) => unknown).bind(stream)
        : value;
    },
    set(stream, property, value) {
      return Reflect.set(stream, property, value, stream);
    },
  }) as NodeJS.WriteStream;
  return { cursor, stdout };
}

export function shouldRunInkTui(args: string[], stdin: NodeJS.ReadStream): boolean {
  if (process.env.KAGENT_CLASSIC_UI) {
    return false;
  }
  if (args.includes("--classic")) {
    return false;
  }
  if (args.length > 0) {
    return false;
  }
  return Boolean(stdin && stdin.isTTY);
}

export async function runKagentInk(_args: string[], options: FallbackOptions = {}): Promise<void> {
  try {
    const React = (await dynamicImport("react")) as typeof import("react");
    const Ink = (await dynamicImport("ink")) as {
      render: (
        element: React.ReactElement,
        options?: { exitOnCtrlC?: boolean; stdout?: NodeJS.WriteStream },
      ) => void;
    };
    const synchronized = process.stdout.isTTY
      ? createCursorSynchronizedStdout(process.stdout)
      : {
          cursor: { update: () => undefined },
          stdout: process.stdout,
        };
    const element = React.createElement(KagentInkApp, {
      React,
      Ink: Ink as never,
      terminalCursor: synchronized.cursor,
    });
    Ink.render(element, {
      exitOnCtrlC: false,
      stdout: synchronized.stdout,
    });
  } catch (error) {
    if (typeof options.fallback === "function") {
      process.stderr.write(`kagent: terminal UI unavailable: ${errorMessage(error)}; using classic CLI\n`);
      options.fallback();
      return;
    }
    throw error;
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

module.exports = {
  createCursorSynchronizedStdout,
  runKagentInk,
  shouldRunInkTui,
};
