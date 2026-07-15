"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createCursorSynchronizedStdout = createCursorSynchronizedStdout;
exports.shouldRunInkTui = shouldRunInkTui;
exports.runKagentInk = runKagentInk;
const App_1 = require("./App");
const dynamicImport = new Function("specifier", "return import(specifier)");
function createCursorSynchronizedStdout(target) {
    let desiredControl = null;
    let positionedControl = null;
    const cursor = {
        update(control) {
            desiredControl = control;
        },
    };
    const stdout = new Proxy(target, {
        get(stream, property) {
            if (property === "write") {
                return (...args) => {
                    if (positionedControl) {
                        stream.write(positionedControl.restore);
                        positionedControl = null;
                    }
                    const result = Reflect.apply(stream.write, stream, args);
                    if (desiredControl) {
                        stream.write(desiredControl.position);
                        positionedControl = desiredControl;
                    }
                    return result;
                };
            }
            const value = Reflect.get(stream, property, stream);
            return typeof value === "function"
                ? value.bind(stream)
                : value;
        },
        set(stream, property, value) {
            return Reflect.set(stream, property, value, stream);
        },
    });
    return { cursor, stdout };
}
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
        const synchronized = process.stdout.isTTY
            ? createCursorSynchronizedStdout(process.stdout)
            : {
                cursor: { update: () => undefined },
                stdout: process.stdout,
            };
        const element = React.createElement(App_1.KagentInkApp, {
            React,
            Ink: Ink,
            terminalCursor: synchronized.cursor,
        });
        Ink.render(element, {
            exitOnCtrlC: false,
            stdout: synchronized.stdout,
        });
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
    createCursorSynchronizedStdout,
    runKagentInk,
    shouldRunInkTui,
};
