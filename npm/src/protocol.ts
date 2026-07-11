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

export type CancelRequest = {
  type: "cancel_request";
  reason?: string;
};

export type SteerRequest = {
  type: "steer_request";
  instruction: string;
};

export type ProviderConfigureRequest = {
  type: "provider_configure";
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
};

export type SessionCommandRequest = {
  type: "session_command";
  command: string;
};

export type RuntimeRequest =
  | RunRequest
  | ApprovalResponseRequest
  | CancelRequest
  | SteerRequest
  | ProviderConfigureRequest
  | SessionCommandRequest;

export type ProviderSnapshot = {
  configured: boolean;
  provider: string;
  display_name: string;
  base_url_configured: boolean;
  model: string;
  api_key_configured: boolean;
};

export type ProviderOption = {
  provider: string;
  label: string;
  base_url: string;
  model: string;
  api_key_required: boolean;
};

export type SessionCommandOption = {
  command: string;
  description: string;
  aliases: string[];
};

export type RunStartedEvent = {
  type: "run_started";
  goal: string;
  max_iterations: string;
};

export type RuntimeReadyEvent = {
  type: "runtime_ready";
  provider: ProviderSnapshot;
  provider_options: ProviderOption[];
  session_commands: SessionCommandOption[];
  pending_approval?: boolean;
  approval_execution_interrupted?: boolean;
};

export type RuntimeUnavailableEvent = {
  type: "runtime_unavailable";
  message: string;
};

export type RunProgressEvent = {
  type: "run_progress";
  event: Record<string, unknown>;
};

export type RunCancelRequestedEvent = {
  type: "run_cancel_requested";
  reason: string;
};

export type RunSteerQueuedEvent = {
  type: "run_steer_queued";
  revision: string;
  replaced: string;
};

export type RunSteerRejectedEvent = {
  type: "run_steer_rejected";
  error_code: string;
  message: string;
  revision?: string;
};

export type ApprovalRequiredEvent = {
  type: "approval_required";
  action_id: string;
  title: string;
  reason: string;
  target: string;
  details?: string[];
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

export type ProviderConfiguredEvent = {
  type: "provider_configured";
  provider: ProviderSnapshot;
};

export type ProviderConfigurationFailedEvent = {
  type: "provider_configuration_failed";
  error_code: string;
  message: string;
  field?: "base_url" | "model" | "api_key";
};

export type SessionCommandCompletedEvent = {
  type: "session_command_completed";
  command: string;
  title: string;
  message: string;
  data: Record<string, unknown>;
  clear_messages: boolean;
};

export type SessionCommandFailedEvent = {
  type: "session_command_failed";
  command: string;
  error_code: string;
  message: string;
};

export type RuntimeProtocolEvent =
  | RuntimeReadyEvent
  | RuntimeUnavailableEvent
  | RunStartedEvent
  | RunProgressEvent
  | RunCancelRequestedEvent
  | RunSteerQueuedEvent
  | RunSteerRejectedEvent
  | ApprovalRequiredEvent
  | RunCompletedEvent
  | RunFailedEvent
  | ProviderConfiguredEvent
  | ProviderConfigurationFailedEvent
  | SessionCommandCompletedEvent
  | SessionCommandFailedEvent;

const EVENT_TYPES = new Set([
  "runtime_ready",
  "runtime_unavailable",
  "run_started",
  "run_progress",
  "run_cancel_requested",
  "run_steer_queued",
  "run_steer_rejected",
  "approval_required",
  "run_completed",
  "run_failed",
  "provider_configured",
  "provider_configuration_failed",
  "session_command_completed",
  "session_command_failed",
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
