from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from kagent.integrations.audit import KafkaRestAuditHook, KafkaRestProgressEventSink


def test_kafka_rest_audit_hook_posts_run_end_event():
    server = _AuditServer()
    server.start()
    try:
        hook = KafkaRestAuditHook(
            url=f"http://127.0.0.1:{server.port}/audit",
            topic="kagent-audit",
            timeout_seconds=1.0,
        )
        hook.on_run_end(
            {
                "run_id": "run-123",
                "goal": "test audit",
                "status": "done",
                "duration_seconds": "0.1",
            }
        )
    finally:
        server.stop()

    assert server.requests == [
        {
            "topic": "kagent-audit",
            "event": {
                "type": "run_end",
                "run_id": "run-123",
                "goal": "test audit",
                "status": "done",
                "duration_seconds": "0.1",
            },
        }
    ]


def test_kafka_rest_progress_event_sink_posts_redacted_runtime_event():
    server = _AuditServer()
    server.start()
    try:
        sink = KafkaRestProgressEventSink(
            url=f"http://127.0.0.1:{server.port}/audit",
            topic="kagent-audit",
            timeout_seconds=1.0,
        )
        sink(
            {
                "run_id": "run-123",
                "type": "tool_completed",
                "tool": "note",
                "status": "ok",
                "input": {"secret": "must-not-leak"},
            }
        )
    finally:
        server.stop()

    assert server.requests == [
        {
            "topic": "kagent-audit",
            "event": {
                "run_id": "run-123",
                "type": "tool_completed",
                "tool": "note",
                "status": "ok",
            },
        }
    ]


class _AuditServer:
    def __init__(self) -> None:
        self.requests = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                outer.requests.append(json.loads(body.decode("utf-8")))
                self.send_response(200)
                self.end_headers()

            def log_message(self, _format, *_args):
                return

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)
