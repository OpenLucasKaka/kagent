"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTerminalInputBridge = createTerminalInputBridge;
const node_readline_1 = require("node:readline");
const node_stream_1 = require("node:stream");
function createTerminalInputBridge(handler) {
    const input = new node_stream_1.PassThrough();
    input.setEncoding("utf8");
    (0, node_readline_1.emitKeypressEvents)(input);
    const handleKeypress = (character, key) => {
        const terminalKey = {
            sequence: key.sequence || "",
            name: key.name,
            ctrl: Boolean(key.ctrl),
            meta: Boolean(key.meta),
            shift: Boolean(key.shift),
        };
        const input = terminalKey.ctrl ? terminalKey.name || "" : printableInput(character);
        handler(input, terminalKey);
    };
    input.on("keypress", handleKeypress);
    return {
        write(chunk) {
            input.write(chunk);
        },
        close() {
            input.removeListener("keypress", handleKeypress);
            input.end();
        },
    };
}
function printableInput(character) {
    if (!character) {
        return "";
    }
    const codePoint = character.codePointAt(0) || 0;
    return codePoint < 32 || codePoint === 127 ? "" : character;
}
