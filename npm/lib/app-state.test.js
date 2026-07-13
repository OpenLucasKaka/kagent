"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const app_state_1 = require("./app-state");
(0, node_test_1.default)("does not render failed run completion as Done", () => {
    const state = (0, app_state_1.appRuntimeReducer)((0, app_state_1.createAppRuntimeState)(), {
        type: "runtime_event",
        channel: "run",
        event: {
            type: "run_completed",
            status: "failed",
            answer: "",
            payload: {
                error: "final_answer is required when actions is empty",
            },
        },
    });
    strict_1.default.equal(state.status, "error");
    strict_1.default.deepEqual(state.transcript.entries.map((entry) => [entry.role, entry.text]), [["system", "final_answer is required when actions is empty"]]);
});
