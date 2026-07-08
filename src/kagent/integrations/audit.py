from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict


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
                "run_id": str(context.get("run_id", "")),
                "goal": str(context.get("goal", "")),
                "status": str(context.get("status", "")),
                "duration_seconds": str(context.get("duration_seconds", "")),
            },
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
