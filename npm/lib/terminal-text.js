"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
exports.splitGraphemes = splitGraphemes;
exports.terminalGraphemeWidth = terminalGraphemeWidth;
exports.terminalSafeText = terminalSafeText;
const string_width_1 = __importDefault(require("string-width"));
const GRAPHEME_SEGMENTER = new Intl.Segmenter(undefined, { granularity: "grapheme" });
function splitGraphemes(value) {
    return Array.from(GRAPHEME_SEGMENTER.segment(value), ({ segment }) => segment);
}
function terminalGraphemeWidth(grapheme) {
    return (0, string_width_1.default)(grapheme);
}
function terminalSafeText(value) {
    return value.replace(/[\u0000-\u001f\u007f-\u009f]/g, "");
}
