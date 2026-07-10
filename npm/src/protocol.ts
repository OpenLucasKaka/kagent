export type RunRequest = {
  type: "run_request";
  goal: string;
  max_iterations?: number;
  runtime_plan?: string;
};

export type ApprovalResponseRequest = {
  type: "approval_response";
  action_id: string;
  approved: boolean;
};

export type RuntimeRequest = RunRequest | ApprovalResponseRequest;

export type RunStartedEvent = {
  type: "run_started";
  goal: string;
  max_iterations: string;
};

export type RuntimeReadyEvent = {
  type: "runtime_ready";
};

export type RuntimeUnavailableEvent = {
  type: "runtime_unavailable";
  message: string;
};

export type RunProgressEvent = {
  type: "run_progress";
  event: Record<string, unknown>;
};

export type ApprovalRequiredEvent = {
  type: "approval_required";
  action_id: string;
  title: string;
  reason: string;
  target: string;
};

export type RunCompletedEvent = {
  type: "run_completed";
  status: string;
  answer: string;
  payload: Record<string, unknown>;
};

export type RunFailedEvent = {
  type: "run_failed";
  error_code: string;
  message: string;
};

export type RuntimeProtocolEvent =
  | RuntimeReadyEvent
  | RuntimeUnavailableEvent
  | RunStartedEvent
  | RunProgressEvent
  | ApprovalRequiredEvent
  | RunCompletedEvent
  | RunFailedEvent;

const EVENT_TYPES = new Set([
  "runtime_ready",
  "runtime_unavailable",
  "run_started",
  "run_progress",
  "approval_required",
  "run_completed",
  "run_failed",
]);

export function parseRuntimeProtocolLine(line: string): RuntimeProtocolEvent | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  const payload = JSON.parse(trimmed) as Record<string, unknown>;
  if (!payload || typeof payload !== "object" || typeof payload.type !== "string") {
    throw new Error("runtime event must include a type");
  }
  if (!EVENT_TYPES.has(payload.type)) {
    throw new Error(`unsupported runtime event: ${payload.type}`);
  }
  return payload as RuntimeProtocolEvent;
}
