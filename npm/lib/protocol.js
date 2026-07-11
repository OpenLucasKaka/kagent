"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.parseRuntimeProtocolLine = parseRuntimeProtocolLine;
const EVENT_TYPES = new Set([
    "runtime_ready",
    "runtime_unavailable",
    "run_started",
    "run_progress",
    "run_cancel_requested",
    "approval_required",
    "run_completed",
    "run_failed",
    "provider_configured",
    "provider_configuration_failed",
    "session_command_completed",
    "session_command_failed",
]);
function parseRuntimeProtocolLine(line) {
    const trimmed = line.trim();
    if (!trimmed) {
        return null;
    }
    const payload = JSON.parse(trimmed);
    if (!payload || typeof payload !== "object" || typeof payload.type !== "string") {
        throw new Error("runtime event must include a type");
    }
    if (!EVENT_TYPES.has(payload.type)) {
        throw new Error(`unsupported runtime event: ${payload.type}`);
    }
    return payload;
}
