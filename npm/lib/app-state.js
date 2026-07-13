"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createAppRuntimeState = createAppRuntimeState;
exports.appRuntimeReducer = appRuntimeReducer;
const provider_setup_1 = require("./provider-setup");
const transcript_1 = require("./transcript");
function createAppRuntimeState() {
    return {
        transcript: (0, transcript_1.createTranscriptState)(),
        status: "starting",
        statusText: "",
        approval: null,
        provider: null,
        setup: null,
        commandCatalog: [],
    };
}
function appRuntimeReducer(state, action) {
    if (action.type === "submit") {
        return {
            ...state,
            transcript: (0, transcript_1.transcriptReducer)(state.transcript, {
                type: "user_submitted",
                text: action.text,
            }),
            status: "thinking",
            statusText: action.command ? "Running command" : "Thinking",
        };
    }
    if (action.type === "setup_action") {
        return state.setup
            ? { ...state, setup: (0, provider_setup_1.providerSetupReducer)(state.setup, action.action) }
            : state;
    }
    if (action.type === "approval_response") {
        return {
            ...state,
            approval: null,
            status: "thinking",
            statusText: action.approved ? "Continuing" : "Cancelling",
        };
    }
    if (action.type === "cancel_requested") {
        return { ...state, status: "cancelling", statusText: action.label };
    }
    if (action.type === "transcript_action") {
        return {
            ...state,
            transcript: (0, transcript_1.transcriptReducer)(state.transcript, action.action),
        };
    }
    if (action.type === "error") {
        return failureState(state, action.message);
    }
    return reduceRuntimeEvent(state, action.channel, action.event);
}
function reduceRuntimeEvent(state, channel, event) {
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
function reduceLifecycleEvent(state, event) {
    if (event.type === "runtime_ready") {
        try {
            return {
                ...state,
                provider: event.provider,
                commandCatalog: event.session_commands || [],
                setup: event.provider.configured
                    ? null
                    : (0, provider_setup_1.createProviderSetupState)(event.provider_options),
                status: "idle",
                statusText: "",
            };
        }
        catch (error) {
            return failureState(state, errorMessage(error));
        }
    }
    if (event.type === "runtime_unavailable" || event.type === "client_failed") {
        return failureState(state, event.message);
    }
    return state;
}
function reduceProviderEvent(state, event) {
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
            setup: (0, provider_setup_1.providerSetupReducer)(state.setup, {
                type: "failure",
                message: event.message,
                field: event.type === "provider_configuration_failed" ? event.field : undefined,
            }),
        };
    }
    return state;
}
function reduceCommandEvent(state, event) {
    if (event.type === "session_command_completed") {
        return {
            ...state,
            status: "idle",
            statusText: "",
            transcript: (0, transcript_1.transcriptReducer)(state.transcript, {
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
function reduceRunEvent(state, event) {
    if (event.type === "run_started") {
        return { ...state, status: "thinking", statusText: "Thinking" };
    }
    if (event.type === "run_progress") {
        const transcriptAction = (0, transcript_1.progressTranscriptAction)(event.event);
        return {
            ...state,
            statusText: progressLabel(event.event),
            transcript: transcriptAction
                ? (0, transcript_1.transcriptReducer)(state.transcript, transcriptAction)
                : state.transcript,
        };
    }
    if (event.type === "run_cancel_requested") {
        return { ...state, status: "cancelling", statusText: "Stopping" };
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
        return { ...state, approval: event, status: "approval", statusText: "" };
    }
    if (event.type === "run_completed") {
        if (event.status !== "done" && event.status !== "cancelled") {
            return failureState({ ...state, approval: null }, runCompletionFailureMessage(event.payload));
        }
        const fallback = event.status === "cancelled" ? "Action cancelled." : "Done.";
        return {
            ...state,
            approval: null,
            status: "idle",
            statusText: "",
            transcript: (0, transcript_1.transcriptReducer)(state.transcript, {
                type: "assistant_completed",
                text: event.answer || fallback,
                outcome: event.status === "cancelled" ? "cancelled" : "complete",
            }),
        };
    }
    if (event.type === "run_failed") {
        const message = event.error_code === "approval_execution_interrupted"
            ? "Action outcome is uncertain. kagent did not retry it. Check the target before trying again."
            : event.message;
        return failureState({ ...state, approval: null }, message);
    }
    if (event.type === "client_failed") {
        return failureState({ ...state, approval: null }, event.message);
    }
    return state;
}
function runCompletionFailureMessage(payload) {
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
function failureState(state, message) {
    return {
        ...state,
        approval: null,
        status: "error",
        statusText: "",
        transcript: (0, transcript_1.transcriptReducer)(state.transcript, { type: "error", text: message }),
    };
}
function progressLabel(event) {
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
function errorMessage(error) {
    return error instanceof Error ? error.message : String(error);
}
