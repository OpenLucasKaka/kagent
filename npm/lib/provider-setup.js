"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.createProviderSetupState = createProviderSetupState;
exports.providerSetupReducer = providerSetupReducer;
exports.selectedProvider = selectedProvider;
exports.providerConfiguration = providerConfiguration;
exports.maskSecret = maskSecret;
exports.isInputStage = isInputStage;
function createProviderSetupState(options) {
    if (options.length === 0) {
        throw new Error("runtime did not provide any model providers");
    }
    return {
        stage: "provider",
        options,
        selectedIndex: 0,
        baseUrl: "",
        model: "",
        apiKey: "",
        editor: { value: "", cursor: 0 },
        error: "",
    };
}
function providerSetupReducer(state, action) {
    if (action.type === "select" && state.stage === "provider") {
        const length = state.options.length;
        const selectedIndex = (state.selectedIndex + action.offset + length) % length;
        return { ...state, selectedIndex, error: "" };
    }
    if (action.type === "edit" && isInputStage(state.stage)) {
        return { ...state, editor: action.editor, error: "" };
    }
    if (action.type === "failure") {
        const stage = action.field ?? "api_key";
        const value = stage === "base_url" ? state.baseUrl : stage === "model" ? state.model : state.apiKey;
        return {
            ...state,
            stage,
            editor: editorFor(value),
            error: action.message,
        };
    }
    if (action.type === "back") {
        return previousStage(state);
    }
    if (action.type === "next") {
        return nextStage(state);
    }
    return state;
}
function selectedProvider(state) {
    return state.options[state.selectedIndex];
}
function providerConfiguration(state) {
    const option = selectedProvider(state);
    return {
        provider: option.provider,
        baseUrl: state.baseUrl,
        model: state.model,
        apiKey: state.apiKey,
    };
}
function maskSecret(value) {
    return splitGraphemes(value).map(() => "•").join("");
}
function isInputStage(stage) {
    return stage === "base_url" || stage === "model" || stage === "api_key";
}
function nextStage(state) {
    const option = selectedProvider(state);
    if (state.stage === "provider") {
        return {
            ...state,
            stage: "base_url",
            baseUrl: "",
            model: "",
            apiKey: "",
            editor: editorFor(""),
            error: "",
        };
    }
    const value = state.editor.value.trim();
    if (state.stage === "base_url") {
        if (!value) {
            return { ...state, error: "Base URL is required." };
        }
        return {
            ...state,
            stage: "model",
            baseUrl: value,
            editor: editorFor(state.model),
            error: "",
        };
    }
    if (state.stage === "model") {
        if (!value) {
            return { ...state, error: "Model is required." };
        }
        return {
            ...state,
            stage: "api_key",
            model: value,
            editor: editorFor(state.apiKey),
            error: "",
        };
    }
    if (state.stage === "api_key") {
        if (option.api_key_required && !value) {
            return { ...state, error: "API key is required for this provider." };
        }
        return {
            ...state,
            stage: "saving",
            apiKey: value,
            editor: { value: "", cursor: 0 },
            error: "",
        };
    }
    return state;
}
function previousStage(state) {
    if (state.stage === "base_url") {
        return { ...state, stage: "provider", editor: editorFor(""), error: "" };
    }
    if (state.stage === "model") {
        return { ...state, stage: "base_url", editor: editorFor(state.baseUrl), error: "" };
    }
    if (state.stage === "api_key" || state.stage === "saving") {
        return { ...state, stage: "model", editor: editorFor(state.model), error: "" };
    }
    return state;
}
function editorFor(value) {
    return { value, cursor: splitGraphemes(value).length };
}
function splitGraphemes(value) {
    const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
    return Array.from(segmenter.segment(value), ({ segment }) => segment);
}
