"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const inkRunner = __importStar(require("./ink-runner"));
(0, node_test_1.default)("synchronizes the terminal cursor at the actual Ink stdout write boundary", () => {
    const createCursorSynchronizedStdout = inkRunner.createCursorSynchronizedStdout;
    strict_1.default.equal(typeof createCursorSynchronizedStdout, "function");
    if (!createCursorSynchronizedStdout) {
        return;
    }
    const writes = [];
    const target = {
        write(value) {
            writes.push(String(value));
            return true;
        },
    };
    const synchronized = createCursorSynchronizedStdout(target);
    synchronized.cursor.update({ position: "position-1", restore: "restore-1" });
    synchronized.stdout.write("frame-1");
    strict_1.default.deepEqual(writes, ["frame-1", "position-1"]);
    synchronized.cursor.update({ position: "position-2", restore: "restore-2" });
    synchronized.stdout.write("frame-2");
    strict_1.default.deepEqual(writes, [
        "frame-1",
        "position-1",
        "restore-1",
        "frame-2",
        "position-2",
    ]);
    synchronized.cursor.update(null);
    synchronized.stdout.write("frame-3");
    strict_1.default.deepEqual(writes, [
        "frame-1",
        "position-1",
        "restore-1",
        "frame-2",
        "position-2",
        "restore-2",
        "frame-3",
    ]);
});
