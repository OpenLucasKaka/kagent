from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict

_AUDIT_EVENT_FIELDS = (
    "run_id",
    "type",
    "node",
    "iteration",
    "action_id",
    "tool",
    "status",
    "error_code",
    "duration_seconds",
    "action_count",
    "iteration_count",
)


@dataclass
class KafkaRestAuditHook:
    url: str
    topic: str
    timeout_seconds: float = 2.0
    fail_closed: bool = False
    failure_count: int = 0

    def on_run_end(self, context: Dict[str, Any]) -> None:
        payload = {
            "topic": self.topic,
            "event": {
                "type": "run_end",
                "run_id": str(context.get("run_id", "")),
                "goal": str(context.get("goal", "")),
                "status": str(context.get("status", "")),
                "duration_seconds": str(context.get("duration_seconds", "")),
            },
        }
        self._post(payload)

    def _post(self, payload: Dict[str, Any]) -> None:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if int(response.status) < 200 or int(response.status) >= 300:
                    raise RuntimeError("audit sink rejected event")
        except Exception:
            self.failure_count += 1
            if self.fail_closed:
                raise


@dataclass
class KafkaRestProgressEventSink:
    url: str
    topic: str
    timeout_seconds: float = 2.0
    fail_closed: bool = False
    failure_count: int = 0

    def __call__(self, event: Dict[str, Any]) -> None:
        payload = {
            "topic": self.topic,
            "event": _redacted_progress_event(event),
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                if int(response.status) < 200 or int(response.status) >= 300:
                    raise RuntimeError("audit sink rejected event")
        except Exception:
            self.failure_count += 1
            if self.fail_closed:
                raise


def _redacted_progress_event(event: Dict[str, Any]) -> Dict[str, str]:
    return {
        field: str(event[field])
        for field in _AUDIT_EVENT_FIELDS
        if field in event and event[field] is not None
    }
