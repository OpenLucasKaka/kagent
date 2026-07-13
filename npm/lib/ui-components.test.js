"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const ui_components_1 = require("./ui-components");
(0, node_test_1.default)("does not reserve session header rows after the intro has been shown", () => {
    const withIntroOverlay = {
        approval: false,
        commandMenu: false,
        introVisible: true,
        prompt: "",
        promptCursor: 0,
    };
    const withoutIntroOverlay = {
        approval: false,
        commandMenu: false,
        introVisible: false,
        prompt: "",
        promptCursor: 0,
    };
    const withIntro = (0, ui_components_1.createTerminalLayout)(100, 30, {
        ...withIntroOverlay,
    });
    const withoutIntro = (0, ui_components_1.createTerminalLayout)(100, 30, {
        ...withoutIntroOverlay,
    });
    strict_1.default.equal(withIntro.reservedRows - withoutIntro.reservedRows, 3);
});
