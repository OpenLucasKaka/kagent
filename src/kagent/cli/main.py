from __future__ import annotations

import argparse
import contextlib
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
from kagent.runtime.metadata import (
    validate_runtime_metadata,
    validate_runtime_tags,
)
from kagent.utils.json_output import format_and_write_json, json_ready

DEFAULT_RUNTIME_MAX_ITERATIONS = 3


def main() -> None:
    warnings.filterwarnings("ignore")

    parser = argparse.ArgumentParser(description="Run the Kagent.")
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
        help="Run the Codex-style plan-act-observe runtime.",
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
        help="Start an interactive runtime shell that reads goals from stdin.",
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
        help="Maximum Codex-style runtime planner iterations.",
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
            FakeLLMProvider,
            LLMProviderConfig,
            OpenAICompatibleProvider,
        )
        from kagent.runtime import run_runtime_agent
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
            _emit_json_payload(agent_topology(), args.output, parser)
            return

        if args.version:
            _emit_json_payload({"version": __version__}, args.output, parser)
            return

        if args.interactive:
            try:
                session_memory_path = _session_memory_path_from_args(
                    args,
                    interactive_tty=sys.stdin.isatty(),
                )
                provider = (
                    FakeLLMProvider(args.runtime_plan)
                    if args.runtime_plan
                    else OpenAICompatibleProvider(LLMProviderConfig.from_env())
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
                    FakeLLMProvider(args.runtime_plan)
                    if args.runtime_plan
                    else OpenAICompatibleProvider(LLMProviderConfig.from_env())
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


def _apply_default_cli_mode(args: argparse.Namespace) -> None:
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
    return bool(args.list_tools or args.list_faults or args.graph or args.version)


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
