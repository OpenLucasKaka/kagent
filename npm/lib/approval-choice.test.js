"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const approval_choice_1 = require("./approval-choice");
(0, node_test_1.default)("moves approval focus with arrow keys", () => {
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("deny", "", "left"), {
        type: "select",
        choice: "allow",
    });
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("allow", "", "right"), {
        type: "select",
        choice: "deny",
    });
});
(0, node_test_1.default)("submits the focused approval choice with enter", () => {
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("allow", "", "enter"), {
        type: "submit",
        approved: true,
    });
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("deny", "", "return"), {
        type: "submit",
        approved: false,
    });
});
(0, node_test_1.default)("keeps direct approval and details shortcuts", () => {
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("deny", "y"), {
        type: "submit",
        approved: true,
    });
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("allow", "n"), {
        type: "submit",
        approved: false,
    });
    strict_1.default.deepEqual((0, approval_choice_1.resolveApprovalInput)("deny", "d"), {
        type: "toggle_details",
    });
});
