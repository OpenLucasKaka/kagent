import hashlib
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from kagent.service import router as service_router
from kagent.service.idempotency import (
    ServiceIdempotencyCache,
    SqliteServiceIdempotencyCache,
)
from kagent.service.runtime import ServiceConfig


def _wait_until(predicate, *, timeout_seconds=1.0):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not met before timeout")


def _assert_single_flight(cache_a, cache_b):
    key = "POST /run\x1f__anonymous__\x1fretry-1"
    body = b'{"goal":"single flight"}'
    execution_count = 0
    execution_lock = threading.Lock()
    owner_started = threading.Event()
    allow_completion = threading.Event()
    start_barrier = threading.Barrier(2)
    distinct_caches = list({id(cache): cache for cache in (cache_a, cache_b)}.values())

    def run(cache):
        nonlocal execution_count
        start_barrier.wait(timeout=1.0)
        status, response, claim_token = cache.acquire(
            key,
            body,
            lease_seconds=2.0,
            wait_timeout_seconds=2.0,
        )
        if status == "hit":
            return status, response
        assert status == "claimed"
        with execution_lock:
            execution_count += 1
            run_id = f"run-{execution_count}"
        owner_started.set()
        assert allow_completion.wait(timeout=2.0)
        payload = {"run_id": run_id, "status": "done"}
        assert cache.complete(key, body, claim_token, 200, payload) is True
        return status, (200, payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, cache) for cache in (cache_a, cache_b)]
        assert owner_started.wait(timeout=1.0)
        _wait_until(
            lambda: sum(
                int(cache.snapshot()["idempotency_cache_waits"])
                for cache in distinct_caches
            )
            == 1
        )
        allow_completion.set()
        results = [future.result(timeout=2.0) for future in futures]

    assert execution_count == 1
    assert sorted(status for status, _response in results) == ["claimed", "hit"]
    assert results[0][1] == results[1][1]


def test_memory_idempotency_cache_serializes_identical_concurrent_requests():
    cache = ServiceIdempotencyCache(max_entries=8)

    _assert_single_flight(cache, cache)


def test_sqlite_idempotency_cache_serializes_across_instances(tmp_path):
    cache_path = tmp_path / "idempotency.sqlite3"

    _assert_single_flight(
        SqliteServiceIdempotencyCache(max_entries=8, database_path=str(cache_path)),
        SqliteServiceIdempotencyCache(max_entries=8, database_path=str(cache_path)),
    )


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_pending_idempotency_key_rejects_different_body_immediately(backend, tmp_path):
    cache = (
        ServiceIdempotencyCache(max_entries=8)
        if backend == "memory"
        else SqliteServiceIdempotencyCache(
            max_entries=8,
            database_path=str(tmp_path / "idempotency.sqlite3"),
        )
    )
    key = "retry-conflict"
    owner_status, _response, owner_token = cache.acquire(
        key,
        b'{"goal":"original"}',
        lease_seconds=2.0,
        wait_timeout_seconds=1.0,
    )

    started_at = time.monotonic()
    status, response, claim_token = cache.acquire(
        key,
        b'{"goal":"different"}',
        lease_seconds=2.0,
        wait_timeout_seconds=1.0,
    )

    assert owner_status == "claimed"
    assert owner_token
    assert status == "conflict"
    assert response is None
    assert claim_token == ""
    assert time.monotonic() - started_at < 0.25


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_waiter_claims_after_failed_owner_releases(backend, tmp_path):
    cache = (
        ServiceIdempotencyCache(max_entries=8)
        if backend == "memory"
        else SqliteServiceIdempotencyCache(
            max_entries=8,
            database_path=str(tmp_path / "idempotency.sqlite3"),
        )
    )
    key = "retry-release"
    body = b'{"goal":"retry after failure"}'
    status, _response, owner_token = cache.acquire(
        key,
        body,
        lease_seconds=2.0,
        wait_timeout_seconds=1.0,
    )
    assert status == "claimed"

    with ThreadPoolExecutor(max_workers=1) as executor:
        waiter = executor.submit(
            cache.acquire,
            key,
            body,
            lease_seconds=2.0,
            wait_timeout_seconds=1.0,
        )
        _wait_until(
            lambda: cache.snapshot()["idempotency_cache_waits"] == "1"
        )
        assert cache.release(key, owner_token) is True
        waiter_status, waiter_response, waiter_token = waiter.result(timeout=1.0)

    assert waiter_status == "claimed"
    assert waiter_response is None
    assert waiter_token and waiter_token != owner_token
    assert cache.complete(key, body, waiter_token, 200, {"run_id": "recovered"}) is True


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_expired_lease_takeover_rejects_stale_owner_completion(backend, tmp_path):
    cache = (
        ServiceIdempotencyCache(max_entries=8)
        if backend == "memory"
        else SqliteServiceIdempotencyCache(
            max_entries=8,
            database_path=str(tmp_path / "idempotency.sqlite3"),
        )
    )
    key = "retry-takeover"
    body = b'{"goal":"take over expired owner"}'
    status, _response, stale_token = cache.acquire(
        key,
        body,
        lease_seconds=0.05,
        wait_timeout_seconds=0.0,
    )
    assert status == "claimed"
    time.sleep(0.075)

    takeover_status, takeover_response, takeover_token = cache.acquire(
        key,
        body,
        lease_seconds=1.0,
        wait_timeout_seconds=0.0,
    )

    assert takeover_status == "claimed"
    assert takeover_response is None
    assert takeover_token and takeover_token != stale_token
    assert cache.complete(key, body, stale_token, 200, {"run_id": "stale"}) is False
    assert cache.complete(key, body, takeover_token, 200, {"run_id": "winner"}) is True
    assert cache.snapshot()["idempotency_cache_takeovers"] == "1"


def test_sqlite_idempotency_cache_migrates_legacy_schema(tmp_path):
    cache_path = tmp_path / "legacy-idempotency.sqlite3"
    body = b'{"goal":"legacy"}'
    fingerprint = hashlib.sha256(body).hexdigest()
    with sqlite3.connect(cache_path) as connection:
        connection.execute(
            "CREATE TABLE idempotency_cache ("
            "cache_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, "
            "status_code INTEGER NOT NULL, payload_json TEXT NOT NULL, "
            "updated_at_ns INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO idempotency_cache VALUES (?, ?, ?, ?, ?)",
            (
                "legacy-key",
                fingerprint,
                200,
                json.dumps({"run_id": "legacy-run"}),
                time.time_ns(),
            ),
        )

    cache = SqliteServiceIdempotencyCache(
        max_entries=8,
        database_path=str(cache_path),
    )

    with sqlite3.connect(cache_path) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(idempotency_cache)")
        }
    assert {"state", "owner_token", "lease_expires_ns"} <= columns
    assert cache.lookup("legacy-key", body) == (
        "hit",
        (200, {"run_id": "legacy-run"}),
    )
    assert cache.acquire(
        "new-key",
        b'{"goal":"new"}',
        lease_seconds=1.0,
        wait_timeout_seconds=0.0,
    )[0] == "claimed"


@pytest.mark.parametrize("backend", ["memory", "sqlite"])
def test_idempotency_wait_timeout_returns_in_progress(backend, tmp_path):
    cache = (
        ServiceIdempotencyCache(max_entries=8)
        if backend == "memory"
        else SqliteServiceIdempotencyCache(
            max_entries=8,
            database_path=str(tmp_path / "idempotency.sqlite3"),
        )
    )
    key = "retry-in-progress"
    body = b'{"goal":"still running"}'
    assert cache.acquire(
        key,
        body,
        lease_seconds=1.0,
        wait_timeout_seconds=0.0,
    )[0] == "claimed"

    status, response, claim_token = cache.acquire(
        key,
        body,
        lease_seconds=1.0,
        wait_timeout_seconds=0.02,
    )

    assert status == "in_progress"
    assert response is None
    assert claim_token == ""
    assert cache.snapshot()["idempotency_cache_wait_timeouts"] == "1"


def test_service_router_returns_same_response_for_concurrent_idempotent_requests():
    cache = ServiceIdempotencyCache(max_entries=8)
    config = ServiceConfig(
        idempotency_cache_size=8,
        run_timeout_seconds=2.0,
        request_timeout_seconds=1.0,
    )
    body = b'{"goal":"run once"}'
    headers = {"Idempotency-Key": "router-single-flight"}
    runner_started = threading.Event()
    allow_runner_completion = threading.Event()
    calls = []

    def runner(goal, _config):
        calls.append(goal)
        runner_started.set()
        assert allow_runner_completion.wait(timeout=1.0)
        return {
            "run_id": "shared-run-id",
            "status": "done",
            "answer": "done",
            "events": [],
            "tool_calls": [],
            "verification_results": [],
            "plan": [],
        }

    def request():
        return service_router.handle_request(
            "POST",
            "/run",
            body,
            headers=headers,
            config=config,
            idempotency_cache=cache,
            agent_runner=runner,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(request)
        assert runner_started.wait(timeout=1.0)
        second = executor.submit(request)
        _wait_until(lambda: cache.snapshot()["idempotency_cache_waits"] == "1")
        allow_runner_completion.set()
        first_response = first.result(timeout=2.0)
        second_response = second.result(timeout=2.0)

    assert calls == ["run once"]
    assert first_response == second_response
    assert first_response[0] == 200
    assert first_response[1]["run_id"] == "shared-run-id"
