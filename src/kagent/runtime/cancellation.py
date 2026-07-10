from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Lock
from typing import Any, Callable, Dict, Mapping, Optional

ExternalCancellationProbe = Callable[[], Optional[Mapping[str, Any]]]


class RuntimeCancellationToken:
    """Thread-safe cooperative cancellation shared across runtime boundaries."""

    def __init__(
        self,
        *,
        external_cancellation_probe: ExternalCancellationProbe | None = None,
    ) -> None:
        self._event = Event()
        self._lock = Lock()
        self._reason = ""
        self._cancelled_at = ""
        self._external_cancellation_probe = external_cancellation_probe

    def cancel(self, reason: str = "", *, cancelled_at: str = "") -> bool:
        normalized_reason = reason.strip()
        normalized_cancelled_at = cancelled_at.strip()
        with self._lock:
            if self._event.is_set():
                return False
            self._reason = normalized_reason
            self._cancelled_at = (
                normalized_cancelled_at or datetime.now(timezone.utc).isoformat()
            )
            self._event.set()
            return True

    def is_cancelled(self) -> bool:
        self._sync_external_cancellation()
        return self._event.is_set()

    def snapshot(self) -> Dict[str, str]:
        self._sync_external_cancellation()
        with self._lock:
            return {
                "cancelled": str(self._event.is_set()).lower(),
                "reason": self._reason,
                "cancelled_at": self._cancelled_at,
            }

    def _sync_external_cancellation(self) -> None:
        if self._event.is_set() or self._external_cancellation_probe is None:
            return
        try:
            cancellation = self._external_cancellation_probe()
        except Exception:
            return
        if not cancellation:
            return
        reason = cancellation.get("reason", cancellation.get("cancel_reason", ""))
        cancelled_at = cancellation.get("cancelled_at", "")
        self.cancel(
            str(reason) if reason is not None else "",
            cancelled_at=str(cancelled_at) if cancelled_at is not None else "",
        )
