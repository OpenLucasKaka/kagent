import { KagentInkApp } from "./App";

type FallbackOptions = {
  fallback?: () => void;
};

type DynamicImport = (specifier: string) => Promise<unknown>;

const dynamicImport = new Function("specifier", "return import(specifier)") as DynamicImport;

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
      render: (element: React.ReactElement, options?: { exitOnCtrlC?: boolean }) => void;
    };
    const element = React.createElement(KagentInkApp, { React, Ink: Ink as never });
    Ink.render(element, { exitOnCtrlC: false });
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
  runKagentInk,
  shouldRunInkTui,
};
