# Remove Provider Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require explicit user configuration for provider, Base URL, model, and API key while preserving product-owned timeout and retry defaults.

**Architecture:** Represent an unconfigured provider as `None`, remove provider inference and endpoint/model presets, and keep the provider catalog limited to adapter identity plus authentication requirements. Both Python and Ink setup flows require an explicit provider selection and blank user-entered endpoint/model values before saving an exact validated configuration.

**Tech Stack:** Python 3.9+, argparse, dataclasses, pytest, TypeScript, React Ink, Node test runner.

---

## File Map

- `src/kagent/providers/llm.py`: explicit provider state, source precedence, strict validation, preset-free catalog.
- `src/kagent/__init__.py`: remove provider inference from the public API.
- `src/kagent/cli/main.py`: require explicit provider selection and blank endpoint/model input.
- `src/kagent/cli/provider.py`: neutral configuration guidance.
- `src/kagent/cli/session_commands.py`: render an optional provider safely.
- `src/kagent/cli/stdio_runtime.py`: expose preset-free options and report provider-field failures.
- `npm/src/protocol.ts`: remove endpoint/model fields from provider options and add provider error targeting.
- `npm/src/provider-setup.ts`: nullable selection and blank editors.
- `npm/src/ui-components.tsx`: render a provider menu with no initial selection.
- `npm/src/provider-setup.test.ts`: focused state-machine regression coverage.
- `tests/test_llm_provider.py`, `tests/test_public_api.py`, `tests/test_cli.py`, `tests/test_stdio_runtime.py`, `tests/test_npm_package.py`: Python and cross-runtime behavior coverage.
- `README.md`, `docs/operations.md`: neutral explicit configuration guidance.

### Task 1: Make Provider Identity Explicit in Python

**Files:**
- Modify: `tests/test_llm_provider.py`
- Modify: `tests/test_public_api.py`
- Modify: `src/kagent/providers/llm.py`
- Modify: `src/kagent/__init__.py`
- Modify: `src/kagent/cli/session_commands.py`

- [ ] **Step 1: Write failing provider-model tests**

Replace inference/default assertions with these tests:

```python
def test_provider_config_has_no_deployment_identity_defaults():
    config = LLMProviderConfig.from_env({})

    assert config.provider is None
    assert config.base_url == ""
    assert config.model == ""
    assert config.api_key == ""
    assert missing_provider_config_fields(config) == [
        "KAGENT_LLM_PROVIDER",
        "KAGENT_LLM_BASE_URL",
        "KAGENT_LLM_MODEL",
    ]


def test_provider_config_does_not_infer_provider_from_endpoint_or_model():
    config = LLMProviderConfig.from_env(
        {
            "KAGENT_LLM_BASE_URL": "https://api.example.test/v1",
            "KAGENT_LLM_MODEL": "test-model",
        }
    )

    assert config.provider is None


def test_provider_identity_environment_presence_clears_saved_values(tmp_path):
    config_path = tmp_path / "provider.json"
    save_provider_config(
        LLMProviderConfig(
            provider=ProviderKind.OPENAI_COMPATIBLE,
            base_url="https://stored.example.test/v1",
            api_key="stored-key",
            model="stored-model",
        ),
        str(config_path),
    )

    config = LLMProviderConfig.from_sources(
        {
            "KAGENT_LLM_PROVIDER": "",
            "KAGENT_LLM_BASE_URL": "",
            "KAGENT_LLM_MODEL": "",
            "KAGENT_LLM_API_KEY": "",
        },
        config_path=str(config_path),
    )

    assert config.provider is None
    assert config.base_url == ""
    assert config.model == ""
    assert config.api_key == ""
```

Add this catalog assertion:

```python
def test_provider_setup_options_contain_no_endpoint_or_model_presets():
    options = provider_setup_options()

    assert all(set(option) == {"provider", "label", "api_key_required"} for option in options)
```

Update the public API test imports and assert `"detect_provider_kind" not in kagent.__all__`.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_llm_provider.py tests/test_public_api.py -q
```

Expected: failures show the implicit OpenAI-compatible provider, inference helper, and
provider option presets still exist.

- [ ] **Step 3: Implement explicit provider state**

Use this config shape:

```python
@dataclass(frozen=True)
class LLMProviderConfig:
    provider: Optional[ProviderKind] = None
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    max_retries: int = 2
    retry_backoff_seconds: float = 0.25

    def __post_init__(self) -> None:
        if self.provider is not None:
            object.__setattr__(self, "provider", normalize_provider_kind(self.provider))
```

`from_env()` must normalize `KAGENT_LLM_PROVIDER` only when non-empty and otherwise set
`provider=None`. `from_sources()` must apply all four deployment identity environment
variables when their keys are present, including empty values. Operational variables
retain their current non-empty override semantics.

Load a missing file as `LLMProviderConfig()`. Load a saved file with a missing/blank
provider as `provider=None`. Call `validate_provider_setup_config()` before saving and
serialize `config.provider.value` only after validation.

Delete `DEFAULT_LLM_MODEL`, `detect_provider_kind()`, `_provider_from_env()`, their public
exports, and tests. Make `provider_display_name(None)` return `"Unconfigured"`.

Return a catalog shaped like:

```python
return [
    {"provider": ProviderKind.QWEN_OPENAI_COMPATIBLE, "label": "Qwen / DashScope", "api_key_required": True},
    {"provider": ProviderKind.DEEPSEEK, "label": "DeepSeek", "api_key_required": True},
    {"provider": ProviderKind.OLLAMA_OPENAI_COMPATIBLE, "label": "Ollama local", "api_key_required": False},
    {"provider": ProviderKind.OPENAI_COMPATIBLE, "label": "OpenAI-compatible / custom", "api_key_required": False},
]
```

`missing_provider_config_fields()` and `validate_provider_setup_config()` must check
provider before provider-specific API-key rules. `build_llm_provider()` must reject
`provider=None` through the same strict validator.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 test command. Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/kagent/providers/llm.py src/kagent/__init__.py src/kagent/cli/session_commands.py tests/test_llm_provider.py tests/test_public_api.py
git commit -m "refactor: require explicit provider identity"
```

### Task 2: Remove Defaults from the Python Setup Flow

**Files:**
- Modify: `tests/test_cli.py`
- Modify: `src/kagent/cli/main.py`
- Modify: `src/kagent/cli/provider.py`

- [ ] **Step 1: Write failing CLI setup tests**

Add these tests:

```python
def test_cli_provider_setup_requires_explicit_provider_selection(tmp_path):
    from kagent.cli.main import _configure_runtime_provider_interactively
    from kagent.providers.llm import LLMProviderConfig

    try:
        _configure_runtime_provider_interactively(
            LLMProviderConfig,
            default_config_path=lambda: str(tmp_path / "provider.json"),
            save_config=lambda config: str(tmp_path / "provider.json"),
            input_fn=lambda _prompt: "",
            secret_input_fn=lambda _prompt: "",
        )
    except ValueError as exc:
        assert str(exc) == "provider selection is required"
    else:
        raise AssertionError("empty provider selection was accepted")


def test_cli_provider_setup_collects_explicit_endpoint_and_model(tmp_path):
    from kagent.cli.main import _configure_runtime_provider_interactively
    from kagent.providers.llm import LLMProviderConfig, ProviderKind

    answers = iter(["2", "https://gateway.example.test/v1", "user-model"])
    saved = []

    config = _configure_runtime_provider_interactively(
        LLMProviderConfig,
        default_config_path=lambda: str(tmp_path / "provider.json"),
        save_config=lambda value: saved.append(value) or str(tmp_path / "provider.json"),
        input_fn=lambda _prompt: next(answers),
        secret_input_fn=lambda _prompt: "user-key",
    )

    assert config.provider == ProviderKind.DEEPSEEK
    assert config.base_url == "https://gateway.example.test/v1"
    assert config.model == "user-model"
    assert config.api_key == "user-key"
    assert saved == [config]


def test_cli_provider_setup_options_have_no_endpoint_or_model_presets():
    from kagent.cli.main import _provider_setup_options

    assert all(
        "base_url" not in option and "model" not in option
        for option in _provider_setup_options()
    )
```

Update missing-config diagnostics to require `KAGENT_LLM_PROVIDER` and neutral placeholder
examples.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
.venv/bin/pytest tests/test_cli.py -k 'provider_setup or provider_config' -q
```

- [ ] **Step 3: Implement explicit CLI input**

Remove every `default_model` parameter and import. The numbered selector prompt becomes
`"Provider: "`; an empty answer raises `ValueError("provider selection is required")`.

Arrow selection uses `selected: int | None = None`. Up selects the final option when
unset, Down selects the first option when unset, and Enter while unset raises the same
required-selection error. Rendering shows no `>` until selection occurs.

Base URL and Model use plain required prompts:

```python
base_url = input_fn("Base URL: ").strip()
model = input_fn("Model: ").strip()
api_key = secret_input_fn("API key: ")
```

Construct and validate the config without substituting catalog values. Rewrite
`runtime_provider_config_message()` with neutral values:

```text
KAGENT_LLM_PROVIDER='your-provider'
KAGENT_LLM_BASE_URL='https://your-endpoint/v1'
KAGENT_LLM_MODEL='your-model'
KAGENT_LLM_API_KEY='your-api-key'
```

- [ ] **Step 4: Verify and commit**

Run the focused CLI command, then:

```bash
git add src/kagent/cli/main.py src/kagent/cli/provider.py tests/test_cli.py
git commit -m "refactor: require explicit CLI provider setup"
```

### Task 3: Tighten the Stdio Provider Protocol

**Files:**
- Modify: `tests/test_stdio_runtime.py`
- Modify: `src/kagent/cli/stdio_runtime.py`
- Modify: `npm/src/protocol.ts`

- [ ] **Step 1: Write failing stdio tests**

Assert `runtime_ready.provider_options` contain only the three catalog fields:

```python
assert all(
    set(option) == {"provider", "label", "api_key_required"}
    for option in events[0]["provider_options"]
)
```

Add a provider-configure test with `provider=""` and these assertions:

```python
event = json.loads(stdout.getvalue().splitlines()[-1])
assert event["type"] == "provider_configuration_failed"
assert event["error_code"] == "invalid_provider_config"
assert event["field"] == "provider"
```

- [ ] **Step 2: Run and verify RED**

```bash
.venv/bin/pytest tests/test_stdio_runtime.py -k provider -q
```

- [ ] **Step 3: Implement protocol changes**

Preserve the API key string supplied in the request instead of applying a product value.
Extend `_provider_error_field()` and `ProviderConfigurationFailedEvent.field` with
`"provider"`. Remove `base_url` and `model` from TypeScript `ProviderOption`.

- [ ] **Step 4: Verify and commit**

```bash
.venv/bin/pytest tests/test_stdio_runtime.py -k provider -q
npm run build:cli
git add src/kagent/cli/stdio_runtime.py npm/src/protocol.ts tests/test_stdio_runtime.py
git commit -m "refactor: tighten provider setup protocol"
```

### Task 4: Require Explicit Selection and Values in Ink

**Files:**
- Create: `npm/src/provider-setup.test.ts`
- Modify: `npm/src/provider-setup.ts`
- Modify: `npm/src/ui-components.tsx`
- Modify: `npm/src/app-state.test.ts`
- Modify: `tests/test_npm_package.py`

- [ ] **Step 1: Write failing TypeScript state tests**

Create this focused test structure:

```typescript
const options: ProviderOption[] = [
  { provider: "openai_compatible", label: "OpenAI-compatible / custom", api_key_required: false },
];

test("requires explicit provider, endpoint, and model input", () => {
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

  state = providerSetupReducer(state, {
    type: "edit",
    editor: {value: "https://gateway.example.test/v1", cursor: 31},
  });
  state = providerSetupReducer(state, {type: "next"});
  assert.equal(state.stage, "model");
  assert.equal(state.editor.value, "");
});
```

- [ ] **Step 2: Run and verify RED**

```bash
npm run build:cli
node --test npm/lib/provider-setup.test.js
```

- [ ] **Step 3: Implement nullable selection**

Change `selectedIndex` to `number | null`. `selectedProvider()` throws
`"Choose a provider."` when no selection exists. Provider-stage `next` returns an error
instead of advancing when selection is null. Selection actions explicitly choose the
first/last option from null. Advancing initializes empty editors and never copies catalog
values.

Move `selectedProvider(setup)` in `ProviderSetupPanel` below the provider-stage branch so
an unselected menu can render. Show no selection marker or bold row while the index is
null, and render `setup.error` under the menu.

Update generated npm integration fixtures to remove option `base_url`/`model` fields and
replace menu-default assertions with explicit input assertions.

- [ ] **Step 4: Verify and commit**

```bash
npm run check
.venv/bin/pytest tests/test_npm_package.py -q
git add npm/src/provider-setup.ts npm/src/provider-setup.test.ts npm/src/ui-components.tsx npm/src/app-state.test.ts tests/test_npm_package.py
git commit -m "refactor: require explicit Ink provider setup"
```

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/operations.md`
- Test: full repository

- [ ] **Step 1: Remove default language and values**

Document the required operator input with neutral placeholders:

```bash
export KAGENT_LLM_PROVIDER='<supported-provider-id>'
export KAGENT_LLM_BASE_URL='https://your-endpoint/v1'
export KAGENT_LLM_MODEL='your-model'
export KAGENT_LLM_API_KEY='your-api-key'
```

Provider adapter names may remain, but no endpoint or model may be described as a
default or pre-filled value.

- [ ] **Step 2: Search for forbidden production defaults**

```bash
rg -n 'DEFAULT_LLM_MODEL|qwen3\.5-122b-a10b|deepseek-chat|"llama3"|dashscope\.aliyuncs\.com/compatible-mode' src npm/src README.md docs/operations.md
```

Expected: no production default/preset matches. Any remaining documentation example must
be explicitly labeled as an example and reviewed manually.

- [ ] **Step 3: Run complete verification**

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest -q
npm run check
bash scripts/run_checks.sh
```

- [ ] **Step 4: Inspect and commit documentation**

```bash
git diff --check
git status --short
git add README.md docs/operations.md
git commit -m "docs: require explicit provider configuration"
```

- [ ] **Step 5: Push the verified branch**

```bash
git push -u origin remove-provider-defaults
```
