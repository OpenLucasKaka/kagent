from __future__ import annotations

from dataclasses import dataclass


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
