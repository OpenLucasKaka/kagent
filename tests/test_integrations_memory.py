from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from kagent.integrations.memory import (
    MilvusLongTermMemory,
    RedisShortTermMemory,
)


def test_redis_short_term_memory_puts_and_gets_json_value():
    server = _RedisCommandServer(
        responses=[
            b"+OK\r\n",
            b"$35\r\n{\"role\":\"user\",\"text\":\"hello kaka\"}\r\n",
        ]
    )
    server.start()
    try:
        memory = RedisShortTermMemory(
            f"redis://127.0.0.1:{server.port}/0",
            timeout_seconds=1.0,
        )

        written = memory.put(
            namespace="session",
            key="run-1",
            value={"role": "user", "text": "hello kaka"},
            ttl_seconds=60,
        )
        read = memory.get(namespace="session", key="run-1")
    finally:
        server.stop()

    assert written == {
        "backend": "redis",
        "namespace": "session",
        "key": "run-1",
        "stored": True,
        "ttl_seconds": "60",
    }
    assert read == {
        "backend": "redis",
        "namespace": "session",
        "key": "run-1",
        "found": True,
        "value": {"role": "user", "text": "hello kaka"},
    }
    assert server.commands == [
        ["SET", "kagent:session:run-1", '{"role":"user","text":"hello kaka"}', "EX", "60"],
        ["GET", "kagent:session:run-1"],
    ]


def test_redis_short_term_memory_reports_missing_value():
    server = _RedisCommandServer(responses=[b"$-1\r\n"])
    server.start()
    try:
        memory = RedisShortTermMemory(
            f"redis://127.0.0.1:{server.port}/0",
            timeout_seconds=1.0,
        )

        read = memory.get(namespace="session", key="missing")
    finally:
        server.stop()

    assert read == {
        "backend": "redis",
        "namespace": "session",
        "key": "missing",
        "found": False,
        "value": None,
    }


def test_milvus_long_term_memory_posts_insert_and_search_requests():
    server = _MilvusRestServer()
    server.start()
    try:
        memory = MilvusLongTermMemory(
            f"http://127.0.0.1:{server.port}",
            timeout_seconds=1.0,
        )

        inserted = memory.upsert(
            collection="kagent_memory",
            memory_id="mem-1",
            text="risk rule accepted",
            vector=[0.1, 0.2],
            metadata={"source": "test"},
        )
        searched = memory.search(
            collection="kagent_memory",
            vector=[0.1, 0.2],
            limit=2,
        )
    finally:
        server.stop()

    assert inserted == {
        "backend": "milvus",
        "collection": "kagent_memory",
        "memory_id": "mem-1",
        "stored": True,
    }
    assert searched == {
        "backend": "milvus",
        "collection": "kagent_memory",
        "matches": [
            {
                "memory_id": "mem-1",
                "text": "risk rule accepted",
                "score": 0.98,
                "metadata": {"source": "test"},
            }
        ],
        "match_count": 1,
    }
    assert server.requests == [
        {
            "path": "/v2/vectordb/entities/insert",
            "body": {
                "collectionName": "kagent_memory",
                "data": [
                    {
                        "id": "mem-1",
                        "text": "risk rule accepted",
                        "vector": [0.1, 0.2],
                        "metadata": {"source": "test"},
                    }
                ],
            },
        },
        {
            "path": "/v2/vectordb/entities/search",
            "body": {
                "collectionName": "kagent_memory",
                "data": [[0.1, 0.2]],
                "limit": 2,
                "outputFields": ["id", "text", "metadata"],
            },
        },
    ]


class _RedisCommandServer:
    def __init__(self, *, responses: list[bytes]) -> None:
        self.commands: list[list[str]] = []
        self._responses = responses
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(len(responses))
        self.port = int(self._socket.getsockname()[1])
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._socket.close()
        self._thread.join(timeout=1)

    def _serve(self) -> None:
        for response in self._responses:
            try:
                conn, _addr = self._socket.accept()
            except OSError:
                return
            with conn:
                payload = conn.recv(4096)
                self.commands.append(_parse_resp_array(payload))
                conn.sendall(response)


def _parse_resp_array(payload: bytes) -> list[str]:
    parts = payload.decode("utf-8").split("\r\n")
    values = []
    index = 1
    while index < len(parts) - 1:
        if parts[index].startswith("$"):
            values.append(parts[index + 1])
            index += 2
        else:
            index += 1
    return values


class _MilvusRestServer:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests.append({"path": self.path, "body": body})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                if self.path.endswith("/search"):
                    response = {
                        "code": 0,
                        "data": [
                            [
                                {
                                    "id": "mem-1",
                                    "text": "risk rule accepted",
                                    "metadata": {"source": "test"},
                                    "distance": 0.98,
                                }
                            ]
                        ],
                    }
                else:
                    response = {"code": 0, "data": {"insertCount": 1}}
                self.wfile.write(json.dumps(response).encode("utf-8"))

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
