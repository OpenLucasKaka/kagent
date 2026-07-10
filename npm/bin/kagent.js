#!/usr/bin/env node
"use strict";

const { runKagentInk, shouldRunInkTui } = require("../lib/ink-runner");
const { runPythonEntrypoint } = require("../lib/python-runner");

const args = process.argv.slice(2);

if (shouldRunInkTui(args, process.stdin)) {
  runKagentInk(args, {
    fallback: () => runPythonEntrypoint("kagent", args)
  });
} else {
  runPythonEntrypoint("kagent", classicArgs(args));
}

function classicArgs(args) {
  return args.filter((arg) => arg !== "--classic");
}
