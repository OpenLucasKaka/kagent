from __future__ import annotations


class RuntimeProviderConfigError(ValueError):
    pass


def runtime_provider_config_message(missing: list[str]) -> str:
    missing_list = ", ".join(missing)
    return (
        "kagent runtime provider is not configured.\n"
        f"Missing: {missing_list}\n\n"
        "Fastest setup:\n"
        "  kagent --configure\n\n"
        "Or set the provider in your shell, then run kagent again:\n"
        "  export KAGENT_LLM_PROVIDER='openai_compatible'\n"
        "  export KAGENT_LLM_BASE_URL='https://your-openai-compatible-endpoint/v1'\n"
        "  export KAGENT_LLM_MODEL='your-model'\n"
        "  export KAGENT_LLM_API_KEY='your-api-key'\n\n"
        "Provider can be openai_compatible, deepseek, qwen, or ollama.\n\n"
        "For a local LLM-free smoke test, run:\n"
        "  kagent 'capture hello' --runtime-plan "
        '\'{"actions":[],"final_answer":"captured hello"}\''
    )


__all__ = ["RuntimeProviderConfigError", "runtime_provider_config_message"]
