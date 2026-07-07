from __future__ import annotations

import argparse
import contextlib
import getpass
import io
import sys
import warnings
from typing import Any

from kagent.cli.interactive import (
    run_runtime_interactive as _run_runtime_interactive,
)
from kagent.cli.memory import default_runtime_session_memory_path
from kagent.cli.trace import (
    persist_runtime_cli_trace,
)
from kagent.cli.trace import (
    persist_runtime_cli_trace_or_raise as _persist_runtime_cli_trace_or_raise,
)
from kagent.cli.ui import runtime_setup_message, runtime_ui_color_enabled
from kagent.runtime.metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from kagent.utils.json_output import format_and_write_json, json_ready

DEFAULT_RUNTIME_MAX_ITERATIONS = 3


class RuntimeProviderConfigError(ValueError):
    pass


def main() -> None:
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description="Run the kagent.")
    parser.add_argument(
        "goal",
        nargs="?",
        help="Goal for the agent, for example: 'calculate 2 + 3'",
    )
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--max-retries", type=int, default=None)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Run the plan-act-observe runtime.",
    )
    parser.add_argument(
        "--deterministic",
        "--legacy-graph",
        action="store_true",
        help="Run the deterministic regression graph instead of the default runtime.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Start the kagent terminal agent that reads goals from stdin.",
    )
    parser.add_argument(
        "--interactive-json",
        action="store_true",
        help="Print full JSON traces in interactive runtime sessions.",
    )
    parser.add_argument(
        "--session-memory",
        default="",
        metavar="PATH",
        help=(
            "Persist interactive runtime session memory to PATH. "
            "Only valid with --runtime --interactive."
        ),
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="Maximum runtime planner iterations.",
    )
    parser.add_argument(
        "--runtime-plan",
        default="",
        metavar="JSON",
        help="Use an inline strict runtime plan JSON payload instead of an LLM provider.",
    )
    parser.add_argument(
        "--tag",
        action="append",
        default=[],
        metavar="TAG",
        help="Attach a non-secret runtime tag; may be repeated.",
    )
    parser.add_argument(
        "--metadata",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Attach non-secret runtime metadata; may be repeated.",
    )
    parser.add_argument(
        "--trace-dir",
        default="",
        metavar="PATH",
        help="Persist one-shot runtime traces to PATH using run_id-based filenames.",
    )
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the registered deterministic tool names as JSON.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print richer metadata for discovery commands that support it.",
    )
    parser.add_argument(
        "--list-faults",
        action="store_true",
        help="Print supported fault injection names as JSON.",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Print the graph topology as JSON.",
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Print the package version as JSON.",
    )
    parser.add_argument(
        "--configure",
        action="store_true",
        help="Configure the local OpenAI-compatible runtime provider.",
    )
    parser.add_argument(
        "--inject-wrong-answer",
        action="append",
        default=[],
        metavar="STEP",
        help="Force one wrong answer for STEP to demonstrate reflection and retry.",
    )
    parser.add_argument(
        "--inject-fault",
        action="append",
        default=[],
        metavar="STEP=FAULT",
        help="Force a named fault for STEP, such as STEP=empty-answer.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a compact run summary instead of the full trace.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print planner output and validation without executing the graph.",
    )
    parser.add_argument(
        "--fail-on-agent-failure",
        action="store_true",
        help="Exit with code 1 when an executed agent run returns failed status.",
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the JSON payload to PATH as well as stdout.",
    )
    args = parser.parse_args()
    _apply_default_cli_mode(args)

    if args.max_steps is not None and args.max_steps < 1:
        parser.error("--max-steps must be at least 1")
    if args.max_retries is not None and args.max_retries < 0:
        parser.error("--max-retries must be non-negative")
    if args.max_iterations is not None and args.max_iterations < 1:
        parser.error("--max-iterations must be at least 1")
    if args.deterministic and (args.runtime or args.runtime_plan):
        parser.error("--deterministic cannot be combined with runtime options")
    if args.deterministic and args.interactive:
        parser.error("--deterministic cannot be combined with --interactive")
    if args.runtime and args.plan:
        parser.error("--plan is not supported with --runtime")
    if args.interactive_json and not args.interactive:
        parser.error("--interactive-json requires --interactive")
    if args.configure and args.goal is not None:
        parser.error("--configure cannot be combined with a goal")
    if args.session_memory and not args.interactive:
        parser.error("--session-memory requires --interactive")
    if args.interactive and args.output:
        parser.error("--output is not supported with --interactive")
    if args.trace_dir and not args.runtime:
        parser.error("--trace-dir requires --runtime")
    if (args.tag or args.metadata) and not args.runtime:
        parser.error("--tag and --metadata require --runtime")
    runtime_metadata, runtime_tags = _runtime_labels_from_args(
        args.metadata,
        args.tag,
        parser,
    )

    if args.goal is not None:
        try:
            fault_plan = _build_fault_plan(args.inject_wrong_answer, args.inject_fault)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        fault_plan = {}

    warning_sink = io.StringIO()
    config_error = ""
    result = {}
    with contextlib.redirect_stderr(warning_sink), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from kagent import __version__
        from kagent.core.agent import (
            AgentConfig,
            agent_topology,
            preview_plan,
            run_agent,
        )
        from kagent.core.faults import SUPPORTED_FAULTS
        from kagent.core.summary import summarize_run
        from kagent.core.tools import (
            registered_tool_metadata,
            registered_tool_names,
        )
        from kagent.providers.llm import (
            DEFAULT_LLM_MODEL,
            FakeLLMProvider,
            LLMProviderConfig,
            build_llm_provider,
            default_provider_config_path,
            save_provider_config,
        )
        from kagent.runtime import run_runtime_agent, runtime_topology
        from kagent.runtime.tools import (
            registered_runtime_tool_metadata,
        )
        from kagent.service.trace_store import persist_trace

        if args.list_tools:
            if args.runtime:
                runtime_tools = registered_runtime_tool_metadata()
                tools = (
                    runtime_tools
                    if args.verbose
                    else [tool["name"] for tool in runtime_tools]
                )
            else:
                tools = registered_tool_metadata() if args.verbose else registered_tool_names()
            _emit_json_payload({"tools": tools}, args.output, parser)
            return

        if args.list_faults:
            _emit_json_payload({"faults": sorted(SUPPORTED_FAULTS)}, args.output, parser)
            return

        if args.graph:
            topology = runtime_topology() if args.runtime else agent_topology()
            _emit_json_payload(topology, args.output, parser)
            return

        if args.version:
            _emit_json_payload({"version": __version__}, args.output, parser)
            return

        if args.configure:
            _configure_runtime_provider_interactively(
                LLMProviderConfig,
                default_model=DEFAULT_LLM_MODEL,
                default_config_path=default_provider_config_path,
                save_config=save_provider_config,
            )
            return

        if args.interactive:
            try:
                session_memory_path = _session_memory_path_from_args(
                    args,
                    interactive_tty=sys.stdin.isatty(),
                )
                provider = (
                    _runtime_provider_from_args(
                        args,
                        FakeLLMProvider,
                        build_llm_provider,
                        LLMProviderConfig,
                        interactive_setup=sys.stdin.isatty(),
                        default_model=DEFAULT_LLM_MODEL,
                        default_config_path=default_provider_config_path,
                        save_config=save_provider_config,
                    )
                )
                _run_runtime_interactive(
                    provider=provider,
                    run_runtime_agent=run_runtime_agent,
                    max_iterations=args.max_iterations or DEFAULT_RUNTIME_MAX_ITERATIONS,
                    fail_on_agent_failure=args.fail_on_agent_failure,
                    full_trace_output=args.interactive_json,
                    metadata=runtime_metadata,
                    tags=runtime_tags,
                    trace_dir=args.trace_dir,
                    persist_trace=persist_trace,
                    session_memory_path=session_memory_path,
                )
                return
            except RuntimeProviderConfigError as exc:
                _exit_runtime_provider_config_error(str(exc))
            except ValueError as exc:
                config_error = str(exc)
            except OSError as exc:
                config_error = f"could not use session memory: {exc}"
        elif args.goal is None:
            parser.error(
                "goal is required unless --interactive, --list-tools, "
                "--list-faults, --graph, or --version is used"
            )

        elif args.runtime:
            try:
                provider = (
                    _runtime_provider_from_args(
                        args,
                        FakeLLMProvider,
                        build_llm_provider,
                        LLMProviderConfig,
                        interactive_setup=sys.stdin.isatty(),
                        default_model=DEFAULT_LLM_MODEL,
                        default_config_path=default_provider_config_path,
                        save_config=save_provider_config,
                    )
                )
                result = run_runtime_agent(
                    args.goal,
                    provider=provider,
                    max_iterations=args.max_iterations or DEFAULT_RUNTIME_MAX_ITERATIONS,
                    metadata=runtime_metadata,
                    tags=runtime_tags,
                )
                if args.trace_dir:
                    _persist_runtime_cli_trace_or_raise(result, args.trace_dir, persist_trace)
            except RuntimeProviderConfigError as exc:
                _exit_runtime_provider_config_error(str(exc))
            except ValueError as exc:
                config_error = str(exc)
            except OSError as exc:
                config_error = f"could not persist --trace-dir trace: {exc}"
        else:
            try:
                config = _config_from_args(AgentConfig, args.max_steps, args.max_retries)
            except ValueError as exc:
                config_error = str(exc)
            else:
                if args.plan:
                    result = preview_plan(args.goal, config=config)
                else:
                    result = run_agent(
                        args.goal,
                        config=config,
                        fault_plan=fault_plan,
                    )
                if args.summary and not args.plan:
                    result = summarize_run(result)
    if config_error:
        parser.error(config_error)
    payload = json_ready(result)
    _emit_json_payload(payload, args.output, parser)
    if args.fail_on_agent_failure and not args.plan and payload.get("status") == "failed":
        raise SystemExit(1)


def _runtime_provider_from_args(
    args: argparse.Namespace,
    FakeLLMProvider,
    build_llm_provider,
    LLMProviderConfig,
    *,
    interactive_setup: bool = False,
    default_model: str = "qwen3.5-122b-a10b",
    default_config_path=None,
    save_config=None,
):
    if args.runtime_plan:
        return FakeLLMProvider(args.runtime_plan)
    config = LLMProviderConfig.from_sources()
    missing = []
    if not config.base_url:
        missing.append("KAGENT_LLM_BASE_URL")
    if not config.model:
        missing.append("KAGENT_LLM_MODEL")
    if missing:
        if interactive_setup and default_config_path is not None and save_config is not None:
            config = _configure_runtime_provider_interactively(
                LLMProviderConfig,
                default_model=default_model,
                default_config_path=default_config_path,
                save_config=save_config,
            )
            missing = []
            if not config.base_url:
                missing.append("KAGENT_LLM_BASE_URL")
            if not config.model:
                missing.append("KAGENT_LLM_MODEL")
            if not missing:
                return build_llm_provider(config)
        raise RuntimeProviderConfigError(_runtime_provider_config_message(missing))
    return build_llm_provider(config)


def _runtime_provider_config_message(missing: list[str]) -> str:
    missing_list = ", ".join(missing)
    return (
        "kagent runtime provider is not configured.\n"
        f"Missing: {missing_list}\n\n"
        "Fastest setup:\n"
        "  kagent --configure\n\n"
        "Or set the provider in your shell, then run kagent again:\n"
        "  export KAGENT_LLM_PROVIDER='openai_compatible'\n"
        "  export KAGENT_LLM_BASE_URL='https://your-openai-compatible-endpoint/v1'\n"
        "  export KAGENT_LLM_MODEL='qwen3.5-122b-a10b'\n"
        "  export KAGENT_LLM_API_KEY='your-api-key'\n\n"
        "Provider can be openai_compatible, deepseek, qwen, or ollama; "
        "kagent can usually infer it from Base URL and model.\n\n"
        "For a local LLM-free smoke test, run:\n"
        "  kagent --deterministic 'calculate 2 + 3'"
    )


def _configure_runtime_provider_interactively(
    LLMProviderConfig,
    *,
    default_model: str,
    default_config_path,
    save_config,
    input_fn=input,
    secret_input_fn=getpass.getpass,
) -> object:
    prompt_stream = sys.__stderr__ or sys.stderr
    config_path = default_config_path()
    print(
        runtime_setup_message(
            config_path=config_path,
            color=runtime_ui_color_enabled(),
        ),
        file=prompt_stream,
    )
    provider_option = _select_provider_for_setup(
        default_model=default_model,
        input_fn=input_fn,
        prompt_stream=prompt_stream,
    )
    provider = provider_option["provider"]
    default_base_url = str(provider_option["base_url"])
    default_provider_model = str(provider_option["model"])
    base_url_prompt = (
        f"Base URL [{default_base_url}]: " if default_base_url else "Base URL: "
    )
    base_url = input_fn(base_url_prompt).strip() or default_base_url
    model = (
        input_fn(f"Model [{default_provider_model}]: ").strip()
        or default_provider_model
    )
    api_key = secret_input_fn("API key: ").strip()
    config = LLMProviderConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
    )
    saved_path = save_config(config)
    print(f"kagent provider config saved to {saved_path}", file=prompt_stream)
    return config


def _select_provider_for_setup(
    *,
    default_model: str,
    input_fn,
    prompt_stream,
) -> dict[str, object]:
    options = _provider_setup_options(default_model)
    if _can_use_arrow_provider_menu(input_fn, prompt_stream):
        return _select_provider_with_arrow_keys(options, prompt_stream)
    print("Select provider:", file=prompt_stream)
    for index, option in enumerate(options, start=1):
        print(
            f"  {index}. {option['label']} ({option['provider'].value})",
            file=prompt_stream,
        )
    answer = input_fn("Provider [1]: ").strip()
    if not answer:
        return options[0]
    try:
        selected_index = int(answer)
    except ValueError as exc:
        raise ValueError("provider selection must be a number") from exc
    if selected_index < 1 or selected_index > len(options):
        raise ValueError("provider selection is out of range")
    return options[selected_index - 1]


def _provider_setup_options(default_model: str) -> list[dict[str, object]]:
    from kagent.providers.llm import ProviderKind

    return [
        {
            "provider": ProviderKind.QWEN_OPENAI_COMPATIBLE,
            "label": "Qwen / DashScope",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": default_model,
        },
        {
            "provider": ProviderKind.DEEPSEEK,
            "label": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat",
        },
        {
            "provider": ProviderKind.OLLAMA_OPENAI_COMPATIBLE,
            "label": "Ollama local",
            "base_url": "http://localhost:11434/v1",
            "model": "llama3",
        },
        {
            "provider": ProviderKind.OPENAI_COMPATIBLE,
            "label": "OpenAI-compatible / custom",
            "base_url": "",
            "model": default_model,
        },
    ]


def _can_use_arrow_provider_menu(input_fn, prompt_stream) -> bool:
    return (
        input_fn is input
        and sys.stdin.isatty()
        and hasattr(prompt_stream, "isatty")
        and prompt_stream.isatty()
    )


def _select_provider_with_arrow_keys(
    options: list[dict[str, object]],
    prompt_stream,
) -> dict[str, object]:
    import termios
    import tty

    input_stream = sys.stdin
    fd = input_stream.fileno()
    old_settings = termios.tcgetattr(fd)
    selected = 0
    print("Select provider with Up/Down, Enter to confirm:", file=prompt_stream)

    def render() -> None:
        print(f"\x1b[{len(options)}A", end="", file=prompt_stream)
        for index, option in enumerate(options):
            marker = ">" if index == selected else " "
            print(
                f"\x1b[2K\r  {marker} {option['label']} ({option['provider'].value})",
                file=prompt_stream,
            )
        prompt_stream.flush()

    try:
        tty.setcbreak(fd)
        print("\x1b[?25l", end="", file=prompt_stream)
        for index, option in enumerate(options):
            marker = ">" if index == selected else " "
            print(
                f"  {marker} {option['label']} ({option['provider'].value})",
                file=prompt_stream,
            )
        prompt_stream.flush()
        while True:
            char = input_stream.read(1)
            if char in {"\r", "\n"}:
                break
            if char == "\x03":
                raise KeyboardInterrupt
            if char != "\x1b":
                continue
            sequence = input_stream.read(2)
            if sequence == "[A":
                selected = (selected - 1) % len(options)
                render()
            elif sequence == "[B":
                selected = (selected + 1) % len(options)
                render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print("\x1b[?25h", end="", file=prompt_stream)
        print(file=prompt_stream)
    return options[selected]


def _exit_runtime_provider_config_error(message: str) -> None:
    print(message, file=sys.__stderr__)
    raise SystemExit(2)


def _apply_default_cli_mode(args: argparse.Namespace) -> None:
    if getattr(args, "configure", False):
        return
    if _uses_deterministic_graph(args):
        args.deterministic = True
        return
    if args.runtime_plan:
        args.runtime = True
    if args.interactive:
        args.runtime = True
    if args.goal is not None and not _is_introspection_command(args):
        args.runtime = True
    if args.goal is None and not _is_introspection_command(args):
        args.runtime = True
        args.interactive = True


def _uses_deterministic_graph(args: argparse.Namespace) -> bool:
    return bool(
        args.deterministic
        or args.plan
        or args.summary
        or args.max_steps is not None
        or args.max_retries is not None
        or args.inject_wrong_answer
        or args.inject_fault
    )


def _is_introspection_command(args: argparse.Namespace) -> bool:
    return bool(
        args.list_tools
        or args.list_faults
        or args.graph
        or args.version
        or getattr(args, "configure", False)
    )


def _session_memory_path_from_args(
    args: argparse.Namespace,
    *,
    interactive_tty: bool,
) -> str:
    if args.session_memory:
        return args.session_memory
    if not interactive_tty:
        return ""
    return default_runtime_session_memory_path()


def _runtime_labels_from_args(
    metadata_items: list[str],
    tag_items: list[str],
    parser: argparse.ArgumentParser,
) -> tuple[dict[str, str], list[str]]:
    raw_metadata = {}
    for item in metadata_items:
        if "=" not in item:
            parser.error("--metadata must use KEY=VALUE")
        key, value = item.split("=", 1)
        raw_metadata[key] = value
    metadata, metadata_error = validate_runtime_metadata(raw_metadata or None)
    if metadata_error:
        parser.error(metadata_error)
    tags, tags_error = validate_runtime_tags(tag_items or None)
    if tags_error:
        parser.error(tags_error)
    return metadata, tags


def _persist_runtime_cli_trace(
    result: dict,
    trace_dir: str,
    persist_trace: Any,
) -> None:
    persist_runtime_cli_trace(result, trace_dir, persist_trace)


def _emit_json_payload(
    payload: Any,
    output_path: str,
    parser: argparse.ArgumentParser,
) -> None:
    try:
        json_payload = format_and_write_json(json_ready(payload), output_path)
    except OSError as exc:
        parser.error(f"could not write --output file: {exc}")
    print(json_payload)


def _build_fault_plan(injected_steps: list, injected_faults: list) -> dict:
    fault_plan = {}
    for step in injected_steps:
        _append_fault(fault_plan, step, "wrong-answer")
    for item in injected_faults:
        step, fault = _parse_fault(item)
        _append_fault(fault_plan, step, fault)
    return fault_plan


def _config_from_args(AgentConfig, max_steps, max_retries):
    config = AgentConfig.from_env()
    return AgentConfig(
        max_steps=max_steps if max_steps is not None else config.max_steps,
        max_retries=max_retries if max_retries is not None else config.max_retries,
    )


def _append_fault(fault_plan: dict, step: str, fault: str) -> None:
    from kagent.core.faults import validate_faults
    from kagent.core.normalization import normalize_goal

    validate_faults([fault])
    normalized_step = normalize_goal(step)
    fault_plan.setdefault(normalized_step, []).append(fault)


def _parse_fault(item: str) -> tuple:
    if "=" not in item:
        raise ValueError("--inject-fault must use STEP=FAULT")
    step, fault = item.rsplit("=", 1)
    return step, fault.strip()


if __name__ == "__main__":
    main()
