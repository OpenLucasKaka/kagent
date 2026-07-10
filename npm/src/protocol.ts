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

export type ProviderConfigureRequest = {
  type: "provider_configure";
  provider: string;
  base_url: string;
  model: string;
  api_key: string;
};

export type RuntimeRequest = RunRequest | ApprovalResponseRequest | ProviderConfigureRequest;

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

export type RunStartedEvent = {
  type: "run_started";
  goal: string;
  max_iterations: string;
};

export type RuntimeReadyEvent = {
  type: "runtime_ready";
  provider: ProviderSnapshot;
  provider_options: ProviderOption[];
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

export type RuntimeProtocolEvent =
  | RuntimeReadyEvent
  | RuntimeUnavailableEvent
  | RunStartedEvent
  | RunProgressEvent
  | ApprovalRequiredEvent
  | RunCompletedEvent
  | RunFailedEvent
  | ProviderConfiguredEvent
  | ProviderConfigurationFailedEvent;

const EVENT_TYPES = new Set([
  "runtime_ready",
  "runtime_unavailable",
  "run_started",
  "run_progress",
  "approval_required",
  "run_completed",
  "run_failed",
  "provider_configured",
  "provider_configuration_failed",
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
