"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.shouldRunInkTui = shouldRunInkTui;
exports.runKagentInk = runKagentInk;
const App_1 = require("./App");
const dynamicImport = new Function("specifier", "return import(specifier)");
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
async function runKagentInk(_args, options = {}) {
    try {
        const React = (await dynamicImport("react"));
        const Ink = (await dynamicImport("ink"));
        const element = React.createElement(App_1.KagentInkApp, { React, Ink: Ink });
        Ink.render(element, { exitOnCtrlC: false });
    }
    catch (error) {
        if (typeof options.fallback === "function") {
            process.stderr.write(`kagent: terminal UI unavailable: ${errorMessage(error)}; using classic CLI\n`);
            options.fallback();
            return;
        }
        throw error;
    }
}
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
module.exports = {
    runKagentInk,
    shouldRunInkTui,
};
