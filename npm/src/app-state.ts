import {
  createProviderSetupState,
  providerSetupReducer,
  type ProviderSetupAction,
  type ProviderSetupState,
} from "./provider-setup";
import type { RuntimeClientEvent } from "./runtime-client";
import type {
  ApprovalRequiredEvent,
  ProviderSnapshot,
  SessionCommandOption,
} from "./protocol";
import {
  createTranscriptState,
  progressTranscriptAction,
  transcriptReducer,
  type TranscriptAction,
  type TranscriptState,
} from "./transcript";
import {
  createRuntimeActivityState,
  reduceRuntimeActivity,
  toggleRuntimeActivity,
  type RuntimeActivityState,
} from "./activity";
import type { AgentStatus } from "./ui-components";

export type AppRuntimeState = {
  transcript: TranscriptState;
  activity: RuntimeActivityState | null;
  status: AgentStatus;
  statusText: string;
  approval: ApprovalRequiredEvent | null;
  provider: ProviderSnapshot | null;
  setup: ProviderSetupState | null;
  commandCatalog: SessionCommandOption[];
};

export type RuntimeEventChannel = "lifecycle" | "provider" | "command" | "run";

export type AppRuntimeAction =
  | { type: "runtime_event"; channel: RuntimeEventChannel; event: RuntimeClientEvent }
  | { type: "submit"; text: string; command: boolean }
  | { type: "setup_action"; action: ProviderSetupAction }
  | { type: "approval_response"; approved: boolean }
  | { type: "cancel_requested"; label: string }
  | { type: "activity_toggle" }
  | { type: "transcript_action"; action: TranscriptAction }
  | { type: "error"; message: string };

export function createAppRuntimeState(): AppRuntimeState {
  return {
    transcript: createTranscriptState(),
    activity: null,
    status: "starting",
    statusText: "",
    approval: null,
    provider: null,
    setup: null,
    commandCatalog: [],
  };
}

export function appRuntimeReducer(
  state: AppRuntimeState,
  action: AppRuntimeAction,
): AppRuntimeState {
  if (action.type === "submit") {
    return {
      ...state,
      transcript: transcriptReducer(state.transcript, {
        type: "user_submitted",
        text: action.text,
      }),
      status: "thinking",
      statusText: action.command ? "Running command" : "Thinking",
      activity: action.command
        ? state.activity
        : activityFor(null, "Preparing your request"),
    };
  }
  if (action.type === "setup_action") {
    return state.setup
      ? { ...state, setup: providerSetupReducer(state.setup, action.action) }
      : state;
  }
  if (action.type === "approval_response") {
    return {
      ...state,
      approval: null,
      status: "thinking",
      statusText: action.approved ? "Continuing" : "Cancelling",
      activity: activityFor(
        state.activity,
        action.approved ? "Continuing" : "Cancelling",
      ),
    };
  }
  if (action.type === "cancel_requested") {
    return {
      ...state,
      status: "cancelling",
      statusText: action.label,
      activity: activityFor(state.activity, "Stopping"),
    };
  }
  if (action.type === "activity_toggle") {
    return state.activity
      ? { ...state, activity: toggleRuntimeActivity(state.activity) }
      : state;
  }
  if (action.type === "transcript_action") {
    return {
      ...state,
      transcript: transcriptReducer(state.transcript, action.action),
    };
  }
  if (action.type === "error") {
    return failureState(state, action.message);
  }
  return reduceRuntimeEvent(state, action.channel, action.event);
}

function reduceRuntimeEvent(
  state: AppRuntimeState,
  channel: RuntimeEventChannel,
  event: RuntimeClientEvent,
): AppRuntimeState {
  if (channel === "lifecycle") {
    return reduceLifecycleEvent(state, event);
  }
  if (channel === "provider") {
    return reduceProviderEvent(state, event);
  }
  if (channel === "command") {
    return reduceCommandEvent(state, event);
  }
  return reduceRunEvent(state, event);
}

function reduceLifecycleEvent(
  state: AppRuntimeState,
  event: RuntimeClientEvent,
): AppRuntimeState {
  if (event.type === "runtime_ready") {
    try {
      return {
        ...state,
        provider: event.provider,
        commandCatalog: event.session_commands || [],
        setup: event.provider.configured
          ? null
          : createProviderSetupState(event.provider_options),
        status: "idle",
        statusText: "",
      };
    } catch (error) {
      return failureState(state, errorMessage(error));
    }
  }
  if (event.type === "runtime_unavailable" || event.type === "client_failed") {
    return failureState(state, event.message);
  }
  return state;
}

function reduceProviderEvent(
  state: AppRuntimeState,
  event: RuntimeClientEvent,
): AppRuntimeState {
  if (event.type === "provider_configured") {
    return {
      ...state,
      provider: event.provider,
      setup: null,
      status: "idle",
      statusText: "",
    };
  }
  if (event.type === "provider_configuration_failed" || event.type === "client_failed") {
    if (!state.setup) {
      return failureState(state, event.message);
    }
    return {
      ...state,
      setup: providerSetupReducer(state.setup, {
        type: "failure",
        message: event.message,
        field: event.type === "provider_configuration_failed" ? event.field : undefined,
      }),
    };
  }
  return state;
}

function reduceCommandEvent(
  state: AppRuntimeState,
  event: RuntimeClientEvent,
): AppRuntimeState {
  if (event.type === "session_command_completed") {
    return {
      ...state,
      status: "idle",
      statusText: "",
      transcript: transcriptReducer(state.transcript, {
        type: "command_completed",
        title: event.title,
        text: event.message,
        clear: event.clear_messages,
      }),
    };
  }
  if (event.type === "session_command_failed" || event.type === "client_failed") {
    return failureState(state, event.message);
  }
  return state;
}

function reduceRunEvent(
  state: AppRuntimeState,
  event: RuntimeClientEvent,
): AppRuntimeState {
  if (event.type === "run_started") {
    return {
      ...state,
      status: "thinking",
      statusText: "Thinking",
      activity: activityFor(null, "Planning next steps"),
    };
  }
  if (event.type === "run_progress") {
    const transcriptAction = progressTranscriptAction(event.event);
    return {
      ...state,
      statusText: progressLabel(event.event),
      activity: reduceRuntimeActivity(
        state.activity ?? createRuntimeActivityState(),
        event.event,
      ),
      transcript: transcriptAction
        ? transcriptReducer(state.transcript, transcriptAction)
        : state.transcript,
    };
  }
  if (event.type === "run_cancel_requested") {
    return {
      ...state,
      status: "cancelling",
      statusText: "Stopping",
      activity: activityFor(state.activity, "Stopping"),
    };
  }
  if (event.type === "run_steer_queued") {
    return {
      ...state,
      status: "thinking",
      statusText: event.replaced === "true" ? "Instruction updated" : "Instruction queued",
    };
  }
  if (event.type === "run_steer_rejected") {
    return {
      ...state,
      statusText: "Instruction was not applied",
    };
  }
  if (event.type === "approval_required") {
    return {
      ...state,
      approval: event,
      status: "approval",
      statusText: "",
      activity: reduceRuntimeActivity(
        state.activity ?? createRuntimeActivityState(),
        event,
      ),
    };
  }
  if (event.type === "run_completed") {
    if (event.status !== "done" && event.status !== "cancelled") {
      return failureState(
        { ...state, approval: null },
        runCompletionFailureMessage(event.payload),
      );
    }
    const fallback = event.status === "cancelled" ? "Action cancelled." : "Done.";
    return {
      ...state,
      approval: null,
      activity: null,
      status: "idle",
      statusText: "",
      transcript: transcriptReducer(state.transcript, {
        type: "assistant_completed",
        text: event.answer || fallback,
        outcome: event.status === "cancelled" ? "cancelled" : "complete",
      }),
    };
  }
  if (event.type === "run_failed") {
    const message =
      event.error_code === "approval_execution_interrupted"
        ? "Action outcome is uncertain. kagent did not retry it. Check the target before trying again."
        : event.message;
    return failureState({ ...state, approval: null }, message);
  }
  if (event.type === "client_failed") {
    return failureState({ ...state, approval: null }, event.message);
  }
  return state;
}

function runCompletionFailureMessage(payload: Record<string, unknown>): string {
  const error = payload.error;
  if (typeof error === "string" && error.trim()) {
    return error;
  }
  const errorCode = payload.error_code;
  if (typeof errorCode === "string" && errorCode.trim()) {
    return errorCode;
  }
  return "Run failed.";
}

function failureState(state: AppRuntimeState, message: string): AppRuntimeState {
  return {
    ...state,
    approval: null,
    activity: null,
    status: "error",
    statusText: "",
    transcript: transcriptReducer(state.transcript, { type: "error", text: message }),
  };
}

function activityFor(
  activity: RuntimeActivityState | null,
  phase: string,
): RuntimeActivityState {
  return reduceRuntimeActivity(activity ?? createRuntimeActivityState(), {
    type: "tool_started",
    presentation: { title: phase },
  });
}

function progressLabel(event: Record<string, unknown>): string {
  const type = String(event.type || "");
  if (type === "steering_applied") {
    return "Updating direction";
  }
  if (type === "planner_started") {
    return "Thinking";
  }
  if (type === "plan_ready") {
    return "Planning next steps";
  }
  if (type === "tool_started") {
    return "Working";
  }
  if (type === "tool_completed") {
    return "Reviewing result";
  }
  return type.endsWith("failed") ? "Retrying" : "Working";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
