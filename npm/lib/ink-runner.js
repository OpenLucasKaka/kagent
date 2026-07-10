"use strict";

const childProcess = require("child_process");
const path = require("path");

function shouldRunInkTui(args, stdin) {
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

async function runKagentInk(args, options) {
  try {
    const React = await import("react");
    const Ink = await import("ink");
    const element = React.createElement(KagentInkApp, {
      React,
      Ink,
      args
    });
    Ink.render(element);
  } catch (error) {
    if (options && typeof options.fallback === "function") {
      process.stderr.write(`kagent: Ink UI unavailable: ${error.message}; using classic CLI\n`);
      return options.fallback();
    }
    throw error;
  }
}

function KagentInkApp({ React, Ink }) {
  const [input, setInput] = React.useState("");
  const [status, setStatus] = React.useState("ready");
  const [output, setOutput] = React.useState("");
  const [running, setRunning] = React.useState(false);
  const app = Ink.useApp();

  Ink.useInput((value, key) => {
    if (running) {
      return;
    }
    if (key.return) {
      const goal = input.trim();
      if (!goal) {
        return;
      }
      if (["exit", "quit", ":q"].includes(goal.toLowerCase())) {
        app.exit();
        return;
      }
      setInput("");
      setRunning(true);
      setStatus("working...");
      setOutput("");
      runClassicRuntime(goal, (event) => {
        if (event.type === "stdout") {
          setOutput((current) => `${current}${event.text}`);
        } else if (event.type === "stderr") {
          setOutput((current) => `${current}${event.text}`);
        } else if (event.type === "exit") {
          setRunning(false);
          setStatus(event.code === 0 ? "ready" : `failed (${event.code})`);
        }
      });
      return;
    }
    if (key.backspace || key.delete) {
      setInput((current) => current.slice(0, -1));
      return;
    }
    if (key.ctrl && value === "c") {
      app.exit();
      return;
    }
    if (value) {
      setInput((current) => `${current}${value}`);
    }
  });

  return React.createElement(
    Ink.Box,
    { flexDirection: "column" },
    React.createElement(Ink.Text, { bold: true }, "kagent"),
    React.createElement(Ink.Text, { color: "gray" }, "local terminal agent"),
    React.createElement(Ink.Text, null, ""),
    React.createElement(
      Ink.Text,
      { color: running ? "cyan" : "green" },
      status
    ),
    output
      ? React.createElement(Ink.Text, null, trimOutput(output))
      : null,
    React.createElement(Ink.Text, null, ""),
    React.createElement(
      Ink.Text,
      null,
      React.createElement(Ink.Text, { color: "cyan" }, "› "),
      input || React.createElement(Ink.Text, { color: "gray" }, "ask kagent")
    )
  );
}

function runClassicRuntime(goal, emit) {
  const scriptPath = path.join(__dirname, "..", "bin", "kagent.js");
  const child = childProcess.spawn(
    process.execPath,
    [scriptPath, "--classic", "--runtime", goal],
    {
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"]
    }
  );
  child.stdout.on("data", (chunk) => emit({ type: "stdout", text: String(chunk) }));
  child.stderr.on("data", (chunk) => emit({ type: "stderr", text: String(chunk) }));
  child.on("error", (error) => {
    emit({ type: "stderr", text: `${error.message}\n` });
    emit({ type: "exit", code: 1 });
  });
  child.on("close", (code) => emit({ type: "exit", code: code === null ? 1 : code }));
}

function trimOutput(output) {
  const lines = String(output).trim().split(/\r?\n/).filter(Boolean);
  return lines.slice(-16).join("\n");
}

module.exports = {
  runKagentInk,
  shouldRunInkTui,
  _internals: {
    KagentInkApp,
    runClassicRuntime,
    trimOutput
  }
};
