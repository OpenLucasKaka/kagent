"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createTerminalInputBridge = createTerminalInputBridge;
const node_readline_1 = require("node:readline");
const node_stream_1 = require("node:stream");
const node_string_decoder_1 = require("node:string_decoder");
const BRACKETED_PASTE_START = "\x1b[200~";
const BRACKETED_PASTE_END = "\x1b[201~";
function createTerminalInputBridge(handler) {
    const input = new node_stream_1.PassThrough();
    const decoder = new node_string_decoder_1.StringDecoder("utf8");
    let pendingInput = "";
    let pastedInput = null;
    input.setEncoding("utf8");
    (0, node_readline_1.emitKeypressEvents)(input);
    const handleKeypress = (character, key) => {
        const terminalKey = normalizeTerminalKey(key);
        const value = terminalKey.ctrl ? terminalKey.name || "" : printableInput(character);
        handler(value, terminalKey);
    };
    input.on("keypress", handleKeypress);
    const emitPaste = (value, sequence) => {
        const normalized = normalizePastedInput(value);
        if (!normalized) {
            return;
        }
        handler(normalized, {
            sequence,
            ctrl: false,
            meta: false,
            shift: false,
        });
    };
    const writeParsedInput = (value) => {
        if (value.length > 1 && !value.includes("\x1b") && /[\r\n]/.test(value)) {
            emitPaste(value, value);
            return;
        }
        input.write(value);
    };
    const consume = (value) => {
        let remaining = pendingInput + value;
        pendingInput = "";
        while (remaining) {
            if (pastedInput !== null) {
                const combined = pastedInput + remaining;
                const endIndex = combined.indexOf(BRACKETED_PASTE_END);
                if (endIndex === -1) {
                    pastedInput = combined;
                    return;
                }
                const completedPaste = combined.slice(0, endIndex);
                emitPaste(completedPaste, BRACKETED_PASTE_START + completedPaste + BRACKETED_PASTE_END);
                pastedInput = null;
                remaining = combined.slice(endIndex + BRACKETED_PASTE_END.length);
                continue;
            }
            const startIndex = remaining.indexOf(BRACKETED_PASTE_START);
            if (startIndex !== -1) {
                writeParsedInput(remaining.slice(0, startIndex));
                pastedInput = "";
                remaining = remaining.slice(startIndex + BRACKETED_PASTE_START.length);
                continue;
            }
            const suffixLength = pasteStartSuffixLength(remaining);
            const parsedEnd = suffixLength > 1 ? remaining.length - suffixLength : remaining.length;
            writeParsedInput(remaining.slice(0, parsedEnd));
            pendingInput = remaining.slice(parsedEnd);
            return;
        }
    };
    return {
        write(chunk) {
            consume(typeof chunk === "string" ? chunk : decoder.write(chunk));
        },
        close() {
            consume(decoder.end());
            writeParsedInput(pendingInput);
            pendingInput = "";
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
function normalizePastedInput(value) {
    return value
        .replace(/\r\n|\r/g, "\n")
        .replace(/\t/g, "  ")
        .replace(/[\u0000-\u0009\u000b-\u001f\u007f]/g, "");
}
function normalizeTerminalKey(key) {
    const sequence = key.sequence || "";
    const modifiedReturn = /^\x1b\[13;(\d+)u$/.exec(sequence);
    if (modifiedReturn) {
        const modifiers = Number(modifiedReturn[1]) - 1;
        return {
            sequence,
            name: "return",
            shift: Boolean(modifiers & 1),
            meta: Boolean(modifiers & 2),
            ctrl: Boolean(modifiers & 4),
        };
    }
    return {
        sequence,
        name: key.name,
        ctrl: Boolean(key.ctrl),
        meta: Boolean(key.meta),
        shift: Boolean(key.shift),
    };
}
function pasteStartSuffixLength(value) {
    const maxLength = Math.min(value.length, BRACKETED_PASTE_START.length - 1);
    for (let length = maxLength; length > 1; length -= 1) {
        if (value.endsWith(BRACKETED_PASTE_START.slice(0, length))) {
            return length;
        }
    }
    return 0;
}
