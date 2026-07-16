import assert from "node:assert/strict";
import test from "node:test";

import {
  createProviderSetupState,
  providerConfiguration,
  providerSetupReducer,
} from "./provider-setup";

const options = [
  {
    provider: "openai_compatible",
    label: "OpenAI-compatible / custom",
    api_key_required: false,
  },
];

test("requires explicit provider endpoint and model input", () => {
  let state = createProviderSetupState(options);

  assert.equal(state.selectedIndex, null);

  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "provider");
  assert.equal(state.error, "Choose a provider.");

  state = providerSetupReducer(state, {type: "select", offset: 1});
  assert.equal(state.selectedIndex, 0);
  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "base_url");
  assert.equal(state.editor.value, "");

  const baseUrl = "https://gateway.example.test/v1";
  state = providerSetupReducer(state, {
    type: "edit",
    editor: {value: baseUrl, cursor: baseUrl.length},
  });
  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "model");
  assert.equal(state.editor.value, "");

  const model = "user-model";
  state = providerSetupReducer(state, {
    type: "edit",
    editor: {value: model, cursor: model.length},
  });
  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "api_key");
  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "saving");

  assert.deepEqual(providerConfiguration(state), {
    provider: "openai_compatible",
    baseUrl,
    model,
    apiKey: "",
  });
});
