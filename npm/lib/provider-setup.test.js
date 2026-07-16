"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const strict_1 = __importDefault(require("node:assert/strict"));
const node_test_1 = __importDefault(require("node:test"));
const provider_setup_1 = require("./provider-setup");
const options = [
    {
        provider: "openai_compatible",
        label: "OpenAI-compatible / custom",
        api_key_required: false,
    },
];
(0, node_test_1.default)("requires explicit provider endpoint and model input", () => {
    let state = (0, provider_setup_1.createProviderSetupState)(options);
    strict_1.default.equal(state.selectedIndex, null);
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "next" });
    strict_1.default.equal(state.stage, "provider");
    strict_1.default.equal(state.error, "Choose a provider.");
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "select", offset: 1 });
    strict_1.default.equal(state.selectedIndex, 0);
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "next" });
    strict_1.default.equal(state.stage, "base_url");
    strict_1.default.equal(state.editor.value, "");
    const baseUrl = "https://gateway.example.test/v1";
    state = (0, provider_setup_1.providerSetupReducer)(state, {
        type: "edit",
        editor: { value: baseUrl, cursor: baseUrl.length },
    });
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "next" });
    strict_1.default.equal(state.stage, "model");
    strict_1.default.equal(state.editor.value, "");
    const model = "user-model";
    state = (0, provider_setup_1.providerSetupReducer)(state, {
        type: "edit",
        editor: { value: model, cursor: model.length },
    });
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "next" });
    strict_1.default.equal(state.stage, "api_key");
    state = (0, provider_setup_1.providerSetupReducer)(state, { type: "next" });
    strict_1.default.equal(state.stage, "saving");
    strict_1.default.deepEqual((0, provider_setup_1.providerConfiguration)(state), {
        provider: "openai_compatible",
        baseUrl,
        model,
        apiKey: "",
    });
});
