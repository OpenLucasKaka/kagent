from __future__ import annotations

from typing import Iterable

SUPPORTED_FAULTS = {"empty-answer", "tool-error", "wrong-answer"}


def validate_faults(faults: Iterable[str]) -> None:
    for fault in faults:
        if fault not in SUPPORTED_FAULTS:
            raise ValueError(f"unsupported fault: {fault}")
