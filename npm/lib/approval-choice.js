"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.resolveApprovalInput = resolveApprovalInput;
function resolveApprovalInput(choice, value, keyName = "") {
    const answer = value.toLowerCase();
    if (answer === "d") {
        return { type: "toggle_details" };
    }
    if (answer === "y") {
        return { type: "submit", approved: true };
    }
    if (answer === "n") {
        return { type: "submit", approved: false };
    }
    if (keyName === "left" || keyName === "up") {
        return { type: "select", choice: "allow" };
    }
    if (keyName === "right" || keyName === "down") {
        return { type: "select", choice: "deny" };
    }
    if (keyName === "enter" || keyName === "return") {
        return { type: "submit", approved: choice === "allow" };
    }
    return null;
}
