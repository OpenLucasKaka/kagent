import type { ProviderConfiguration } from "./runtime-client";
import type { ProviderOption } from "./protocol";

export type SetupStage = "provider" | "base_url" | "model" | "api_key" | "saving";

export type SetupEditor = {
  value: string;
  cursor: number;
};

export type ProviderSetupState = {
  stage: SetupStage;
  options: ProviderOption[];
  selectedIndex: number | null;
  baseUrl: string;
  model: string;
  apiKey: string;
  editor: SetupEditor;
  error: string;
};

export type ProviderSetupAction =
  | { type: "select"; offset: number }
  | { type: "edit"; editor: SetupEditor }
  | { type: "next" }
  | { type: "back" }
  | {
      type: "failure";
      message: string;
      field?: "provider" | "base_url" | "model" | "api_key";
    };

export function createProviderSetupState(options: ProviderOption[]): ProviderSetupState {
  if (options.length === 0) {
    throw new Error("runtime did not provide any model providers");
  }
  return {
    stage: "provider",
    options,
    selectedIndex: null,
    baseUrl: "",
    model: "",
    apiKey: "",
    editor: { value: "", cursor: 0 },
    error: "",
  };
}

export function providerSetupReducer(
  state: ProviderSetupState,
  action: ProviderSetupAction,
): ProviderSetupState {
  if (action.type === "select" && state.stage === "provider") {
    const length = state.options.length;
    const selectedIndex = state.selectedIndex === null
      ? action.offset < 0 ? length - 1 : 0
      : (state.selectedIndex + action.offset + length) % length;
    return { ...state, selectedIndex, error: "" };
  }
  if (action.type === "edit" && isInputStage(state.stage)) {
    return { ...state, editor: action.editor, error: "" };
  }
  if (action.type === "failure") {
    if (action.field === "provider") {
      return {
        ...state,
        stage: "provider",
        editor: editorFor(""),
        error: action.message,
      };
    }
    const stage = action.field ?? "api_key";
    const value =
      stage === "base_url" ? state.baseUrl : stage === "model" ? state.model : state.apiKey;
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

export function selectedProvider(state: ProviderSetupState): ProviderOption {
  if (state.selectedIndex === null) {
    throw new Error("Choose a provider.");
  }
  return state.options[state.selectedIndex];
}

export function providerConfiguration(state: ProviderSetupState): ProviderConfiguration {
  const option = selectedProvider(state);
  return {
    provider: option.provider,
    baseUrl: state.baseUrl,
    model: state.model,
    apiKey: state.apiKey,
  };
}

export function maskSecret(value: string): string {
  return splitGraphemes(value).map(() => "•").join("");
}

export function isInputStage(stage: SetupStage): boolean {
  return stage === "base_url" || stage === "model" || stage === "api_key";
}

function nextStage(state: ProviderSetupState): ProviderSetupState {
  if (state.stage === "provider") {
    if (state.selectedIndex === null) {
      return { ...state, error: "Choose a provider." };
    }
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
  const option = selectedProvider(state);
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

function previousStage(state: ProviderSetupState): ProviderSetupState {
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

function editorFor(value: string): SetupEditor {
  return { value, cursor: splitGraphemes(value).length };
}

function splitGraphemes(value: string): string[] {
  const segmenter = new Intl.Segmenter(undefined, { granularity: "grapheme" });
  return Array.from(segmenter.segment(value), ({ segment }) => segment);
}
