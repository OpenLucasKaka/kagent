from __future__ import annotations

import json
import socket
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List

_KEY_PART_MAX_LENGTH = 120
_TEXT_MAX_LENGTH = 20000
_VECTOR_MAX_ITEMS = 4096


@dataclass(frozen=True)
class RedisShortTermMemory:
    url: str
    timeout_seconds: float = 2.0
    key_prefix: str = "kagent"

    def put(
        self,
        *,
        namespace: str,
        key: str,
        value: Any,
        ttl_seconds: int = 0,
    ) -> Dict[str, Any]:
        normalized_namespace = _validate_key_part(namespace, "namespace")
        normalized_key = _validate_key_part(key, "key")
        normalized_ttl = _validate_ttl(ttl_seconds)
        redis_key = self._redis_key(normalized_namespace, normalized_key)
        encoded_value = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        command = ["SET", redis_key, encoded_value]
        if normalized_ttl > 0:
            command.extend(["EX", str(normalized_ttl)])
        response = self._execute(command)
        if response != "OK":
            raise RuntimeError("redis did not acknowledge memory write")
        return {
            "backend": "redis",
            "namespace": normalized_namespace,
            "key": normalized_key,
            "stored": True,
            "ttl_seconds": str(normalized_ttl),
        }

    def get(self, *, namespace: str, key: str) -> Dict[str, Any]:
        normalized_namespace = _validate_key_part(namespace, "namespace")
        normalized_key = _validate_key_part(key, "key")
        response = self._execute(["GET", self._redis_key(normalized_namespace, normalized_key)])
        if response is None:
            return {
                "backend": "redis",
                "namespace": normalized_namespace,
                "key": normalized_key,
                "found": False,
                "value": None,
            }
        try:
            value = json.loads(response)
        except json.JSONDecodeError:
            value = response
        return {
            "backend": "redis",
            "namespace": normalized_namespace,
            "key": normalized_key,
            "found": True,
            "value": value,
        }

    def _redis_key(self, namespace: str, key: str) -> str:
        return f"{self.key_prefix}:{namespace}:{key}"

    def _execute(self, command: List[str]) -> Any:
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme != "redis":
            raise ValueError("redis url must use redis://")
        if not parsed.hostname:
            raise ValueError("redis url host is required")
        port = parsed.port or 6379
        with socket.create_connection(
            (parsed.hostname, port),
            timeout=self.timeout_seconds,
        ) as conn:
            conn.settimeout(self.timeout_seconds)
            conn.sendall(_encode_resp_array(command))
            response = _read_resp(conn)
        if isinstance(response, Exception):
            raise response
        return response


@dataclass(frozen=True)
class MilvusLongTermMemory:
    url: str
    timeout_seconds: float = 2.0

    def upsert(
        self,
        *,
        collection: str,
        memory_id: str,
        text: str,
        vector: List[float],
        metadata: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        normalized_collection = _validate_key_part(collection, "collection")
        normalized_id = _validate_key_part(memory_id, "memory_id")
        normalized_text = _validate_text(text)
        normalized_vector = _validate_vector(vector)
        payload = {
            "collectionName": normalized_collection,
            "data": [
                {
                    "id": normalized_id,
                    "text": normalized_text,
                    "vector": normalized_vector,
                    "metadata": metadata or {},
                }
            ],
        }
        self._post("/v2/vectordb/entities/insert", payload)
        return {
            "backend": "milvus",
            "collection": normalized_collection,
            "memory_id": normalized_id,
            "stored": True,
        }

    def search(
        self,
        *,
        collection: str,
        vector: List[float],
        limit: int = 5,
    ) -> Dict[str, Any]:
        normalized_collection = _validate_key_part(collection, "collection")
        normalized_vector = _validate_vector(vector)
        normalized_limit = _validate_limit(limit)
        payload = {
            "collectionName": normalized_collection,
            "data": [normalized_vector],
            "limit": normalized_limit,
            "outputFields": ["id", "text", "metadata"],
        }
        response = self._post("/v2/vectordb/entities/search", payload)
        matches = _milvus_matches(response)
        return {
            "backend": "milvus",
            "collection": normalized_collection,
            "matches": matches,
            "match_count": len(matches),
        }

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        endpoint = self._endpoint(path)
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, sort_keys=True).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read(1024 * 1024).decode("utf-8")
            if int(response.status) < 200 or int(response.status) >= 300:
                raise RuntimeError("milvus request failed")
        parsed = json.loads(body or "{}")
        if not isinstance(parsed, dict):
            raise RuntimeError("milvus response must be a JSON object")
        code = parsed.get("code", 0)
        if code not in (0, "0", None):
            raise RuntimeError(f"milvus request failed: code={code}")
        return parsed

    def _endpoint(self, path: str) -> str:
        parsed = urllib.parse.urlparse(self.url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("milvus url must use http:// or https://")
        return urllib.parse.urljoin(self.url.rstrip("/") + "/", path.lstrip("/"))


def _validate_key_part(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    if len(normalized) > _KEY_PART_MAX_LENGTH:
        raise ValueError(f"{field_name} is too long")
    if any(char in normalized for char in "/\\ \t\r\n:"):
        raise ValueError(f"{field_name} contains unsafe characters")
    return normalized


def _validate_text(value: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError("text is required")
    if len(normalized) > _TEXT_MAX_LENGTH:
        raise ValueError("text is too long")
    return normalized


def _validate_vector(vector: List[float]) -> List[float]:
    if not isinstance(vector, list) or not vector:
        raise ValueError("vector must be a non-empty list")
    if len(vector) > _VECTOR_MAX_ITEMS:
        raise ValueError("vector is too long")
    normalized = []
    for item in vector:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValueError("vector must contain only numbers")
        normalized.append(float(item))
    return normalized


def _validate_ttl(ttl_seconds: int) -> int:
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ValueError("ttl_seconds must be an integer")
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be non-negative")
    return ttl_seconds


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    if limit < 1 or limit > 50:
        raise ValueError("limit must be between 1 and 50")
    return limit


def _encode_resp_array(parts: List[str]) -> bytes:
    chunks = [f"*{len(parts)}\r\n".encode("utf-8")]
    for part in parts:
        encoded = str(part).encode("utf-8")
        chunks.append(f"${len(encoded)}\r\n".encode("utf-8"))
        chunks.append(encoded + b"\r\n")
    return b"".join(chunks)


def _read_resp(conn: socket.socket) -> Any:
    prefix = conn.recv(1)
    if prefix == b"+":
        return _read_line(conn)
    if prefix == b"$":
        length = int(_read_line(conn))
        if length == -1:
            return None
        data = _recv_exact(conn, length)
        _recv_exact(conn, 2)
        return data.decode("utf-8")
    if prefix == b"-":
        return RuntimeError(_read_line(conn))
    raise RuntimeError("unsupported redis response")


def _read_line(conn: socket.socket) -> str:
    data = bytearray()
    while not data.endswith(b"\r\n"):
        chunk = conn.recv(1)
        if not chunk:
            raise RuntimeError("connection closed while reading redis response")
        data.extend(chunk)
    return data[:-2].decode("utf-8")


def _recv_exact(conn: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            raise RuntimeError("connection closed while reading redis response")
        data.extend(chunk)
    return bytes(data)


def _milvus_matches(response: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = response.get("data", [])
    if data and isinstance(data[0], list):
        rows = data[0]
    else:
        rows = data
    matches = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        memory_id = row.get("id", row.get("memory_id", ""))
        matches.append(
            {
                "memory_id": str(memory_id),
                "text": str(row.get("text", "")),
                "score": float(row.get("score", row.get("distance", 0.0))),
                "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
            }
        )
    return matches
