"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.terminalGraphemeWidth = void 0;
exports.estimateTextRows = estimateTextRows;
const terminal_text_1 = require("./terminal-text");
function estimateTextRows(text, columns) {
    const safeColumns = Math.max(1, columns);
    return text.split("\n").reduce((total, line) => {
        const width = (0, terminal_text_1.splitGraphemes)(line).reduce((lineWidth, grapheme) => lineWidth + (0, terminal_text_1.terminalGraphemeWidth)(grapheme), 0);
        return total + Math.max(1, Math.ceil(width / safeColumns));
    }, 0);
}
var terminal_text_2 = require("./terminal-text");
Object.defineProperty(exports, "terminalGraphemeWidth", { enumerable: true, get: function () { return terminal_text_2.terminalGraphemeWidth; } });
