"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.estimateTextRows = estimateTextRows;
exports.terminalGraphemeWidth = terminalGraphemeWidth;
const editor_1 = require("./editor");
function estimateTextRows(text, columns) {
    const safeColumns = Math.max(1, columns);
    return text.split("\n").reduce((total, line) => {
        const width = (0, editor_1.splitGraphemes)(line).reduce((lineWidth, grapheme) => lineWidth + terminalGraphemeWidth(grapheme), 0);
        return total + Math.max(1, Math.ceil(width / safeColumns));
    }, 0);
}
function terminalGraphemeWidth(grapheme) {
    const codePoint = grapheme.codePointAt(0) || 0;
    if (codePoint >= 0x1100 &&
        (codePoint <= 0x115f ||
            codePoint === 0x2329 ||
            codePoint === 0x232a ||
            (codePoint >= 0x2e80 && codePoint <= 0xa4cf) ||
            (codePoint >= 0xac00 && codePoint <= 0xd7a3) ||
            (codePoint >= 0xf900 && codePoint <= 0xfaff) ||
            (codePoint >= 0xfe10 && codePoint <= 0xfe6f) ||
            (codePoint >= 0xff00 && codePoint <= 0xff60) ||
            (codePoint >= 0x1f300 && codePoint <= 0x1faff))) {
        return 2;
    }
    return 1;
}
