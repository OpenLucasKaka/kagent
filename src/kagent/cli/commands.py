from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches


@dataclass(frozen=True)
class RuntimeInteractiveCommand:
    primary: str
    description: str
    section: str
    aliases: tuple[str, ...] = ()


_RUNTIME_INTERACTIVE_COMMANDS: tuple[RuntimeInteractiveCommand, ...] = (
    RuntimeInteractiveCommand("/pwd", "show working directory", "Session", ("/cwd",)),
    RuntimeInteractiveCommand("/cd PATH", "change working directory", "Session", ("/cd",)),
    RuntimeInteractiveCommand("/status", "show shell state", "Session", ("/stat",)),
    RuntimeInteractiveCommand("/memory", "review remembered turns", "Session", ("/mem",)),
    RuntimeInteractiveCommand("/clear", "clear remembered turns", "Session", ("/clear-memory",)),
    RuntimeInteractiveCommand(
        "/reset",
        "clear memory and prompt history",
        "Session",
        ("/reset-session",),
    ),
    RuntimeInteractiveCommand("/last", "replay last answer", "Session", ("/last-run",)),
    RuntimeInteractiveCommand(
        "/config",
        "show redacted provider config",
        "Provider",
        ("/provider",),
    ),
    RuntimeInteractiveCommand("/tools", "show available actions", "Provider", ("/actions",)),
    RuntimeInteractiveCommand(
        "/compact",
        "clean transcript",
        "Output",
        ("/summary",),
    ),
    RuntimeInteractiveCommand(
        "/json",
        "full JSON traces",
        "Output",
        ("/full", "/debug"),
    ),
    RuntimeInteractiveCommand("/trace", "last JSON trace once", "Output", ("/last-json",)),
    RuntimeInteractiveCommand(
        "/save-trace PATH",
        "save last JSON trace",
        "Output",
        ("/export-trace",),
    ),
    RuntimeInteractiveCommand(
        "/doctor",
        "show local diagnostics",
        "Debug",
        ("/diagnostics",),
    ),
    RuntimeInteractiveCommand("/help", "command palette", "Debug", ("/?",)),
    RuntimeInteractiveCommand("exit", "quit", "Debug", ("quit", ":q")),
)


def runtime_interactive_commands() -> tuple[RuntimeInteractiveCommand, ...]:
    return _RUNTIME_INTERACTIVE_COMMANDS


def runtime_interactive_completion_words() -> list[str]:
    words: list[str] = []
    for command in _RUNTIME_INTERACTIVE_COMMANDS:
        for word in (command.primary.split()[0], *command.aliases):
            if word not in words:
                words.append(word)
    return words


def is_runtime_interactive_command(text: str) -> bool:
    command_name = _runtime_command_name(text)
    if not command_name:
        return False
    return command_name in runtime_interactive_completion_words()


def runtime_interactive_command_suggestions(text: str) -> list[str]:
    command_name = _runtime_command_name(text)
    if not command_name:
        return []
    return get_close_matches(
        command_name,
        runtime_interactive_completion_words(),
        n=3,
        cutoff=0.55,
    )


def _runtime_command_name(text: str) -> str:
    return str(text).strip().split(maxsplit=1)[0].lower()
