from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator

from kagent.runtime import RUNTIME_TRACE_TYPE
from kagent.service.safety import (
    safe_trace_file_stem,
)
from kagent.utils.json_output import format_and_write_json, json_ready

DEFAULT_RUNTIME_RETENTION_STATUSES = ("cancelled", "done", "failed", "resumed")


def trace_path_for_run_id(run_id: Any, trace_dir: str) -> Path:
    return Path(trace_dir) / f"{safe_trace_file_stem(run_id)}.json"


@contextmanager
def runtime_trace_lock(run_id: Any, trace_dir: str) -> Iterator[None]:
    """Serialize cross-process read/modify/write operations for one runtime trace."""

    output_dir = Path(trace_dir)
    _ensure_owner_only_trace_dir(output_dir)
    lock_path = output_dir / f".{safe_trace_file_stem(run_id)}.runtime.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    lock_fd = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)


def persist_trace(trace: Dict[str, Any], trace_dir: str) -> str:
    output_dir = Path(trace_dir)
    _ensure_owner_only_trace_dir(output_dir)
    output_path = trace_path_for_run_id(trace.get("run_id"), trace_dir)
    temporary_path = _write_owner_only_temporary_trace(
        output_dir,
        output_path.name,
        json.dumps(json_ready(trace), sort_keys=True) + "\n",
    )
    try:
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return str(output_path)


def load_trace_by_run_id(run_id: Any, trace_dir: str) -> Dict[str, Any] | None:
    trace_path = trace_path_for_run_id(run_id, trace_dir)
    if trace_path.is_symlink():
        raise OSError("trace file must not be a symlink")
    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(payload, dict):
        raise ValueError("trace payload must be a JSON object")
    return payload


def _ensure_owner_only_trace_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)


def _write_owner_only_temporary_trace(output_dir: Path, output_name: str, data: str) -> Path:
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{output_name}.",
        suffix=".tmp",
        dir=output_dir,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if fd != -1:
            os.close(fd)
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def prune_traces(
    trace_dir: str | Path,
    *,
    max_age_seconds: float,
    now: float | None = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    output_dir = Path(trace_dir)
    current_time = time.time() if now is None else now
    cutoff = current_time - max_age_seconds
    scanned = 0
    matched = 0
    deleted = 0
    errors = []

    for path in sorted(output_dir.glob("*.json")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        scanned += 1
        if path.stat().st_mtime > cutoff:
            continue
        matched += 1
        if dry_run:
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})

    return {
        "trace_dir": str(output_dir),
        "max_age_seconds": int(max_age_seconds),
        "dry_run": dry_run,
        "scanned": scanned,
        "matched": matched,
        "deleted": deleted,
        "kept": scanned - matched,
        "errors": errors,
    }


def prune_runtime_traces(
    trace_dir: str | Path,
    *,
    max_age_seconds: float,
    statuses: tuple[str, ...] = DEFAULT_RUNTIME_RETENTION_STATUSES,
    now: float | None = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    if max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    normalized_statuses = tuple(sorted({status for status in statuses if status}))
    if not normalized_statuses:
        raise ValueError("statuses must contain at least one runtime status")
    output_dir = Path(trace_dir)
    current_time = time.time() if now is None else now
    cutoff = current_time - max_age_seconds
    scanned = 0
    runtime_scanned = 0
    matched = 0
    deleted = 0
    protected_pending = 0
    skipped_non_runtime = 0
    skipped_fresh = 0
    skipped_status = 0
    unreadable = 0
    matched_by_status: Dict[str, str] = {}
    errors = []

    for path in sorted(output_dir.glob("*.json")):
        if path.is_symlink():
            continue
        if not path.is_file():
            continue
        scanned += 1
        try:
            trace = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            unreadable += 1
            errors.append({"path": str(path), "error": str(exc)})
            continue
        if not isinstance(trace, dict):
            unreadable += 1
            errors.append({"path": str(path), "error": "trace payload must be a JSON object"})
            continue
        if trace.get("trace_type") != RUNTIME_TRACE_TYPE:
            skipped_non_runtime += 1
            continue
        runtime_scanned += 1
        status = str(trace.get("status", ""))
        if status == "requires_approval" and status not in normalized_statuses:
            protected_pending += 1
            skipped_status += 1
            continue
        if status not in normalized_statuses:
            skipped_status += 1
            continue
        if path.stat().st_mtime > cutoff:
            skipped_fresh += 1
            continue
        matched += 1
        matched_by_status[status] = str(int(matched_by_status.get(status, "0")) + 1)
        if dry_run:
            continue
        try:
            path.unlink()
            deleted += 1
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})

    return {
        "trace_dir": str(output_dir),
        "max_age_seconds": int(max_age_seconds),
        "dry_run": dry_run,
        "statuses": list(normalized_statuses),
        "scanned": scanned,
        "runtime_scanned": runtime_scanned,
        "matched": matched,
        "deleted": deleted,
        "kept": scanned - matched,
        "protected_pending": protected_pending,
        "skipped_non_runtime": skipped_non_runtime,
        "skipped_fresh": skipped_fresh,
        "skipped_status": skipped_status,
        "unreadable": unreadable,
        "matched_by_status": matched_by_status,
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prune persisted kagent trace JSON files."
    )
    parser.add_argument("trace_dir", help="Trace directory to scan.")
    parser.add_argument(
        "--max-age-days",
        type=float,
        required=True,
        help="Match trace JSON files older than this many days.",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete matched traces. Without this flag the command is a dry run.",
    )
    parser.add_argument(
        "--runtime-only",
        action="store_true",
        help=(
            "Prune only Codex-style runtime traces. By default this matches old "
            "done, failed, and cancelled runs while protecting requires_approval."
        ),
    )
    parser.add_argument(
        "--statuses",
        default=",".join(DEFAULT_RUNTIME_RETENTION_STATUSES),
        help=(
            "Comma-separated runtime statuses matched with --runtime-only. "
            "Defaults to cancelled,done,failed,resumed."
        ),
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Write the JSON summary to PATH as well as stdout.",
    )
    parser.add_argument(
        "--fail-on-errors",
        action="store_true",
        help=(
            "Exit with status 1 after writing the summary when unreadable traces "
            "or delete errors are reported."
        ),
    )
    args = parser.parse_args()
    if args.max_age_days < 0:
        parser.error("--max-age-days must be non-negative")
    if args.runtime_only:
        statuses = tuple(status.strip() for status in args.statuses.split(",") if status.strip())
        summary = prune_runtime_traces(
            args.trace_dir,
            max_age_seconds=args.max_age_days * 24 * 60 * 60,
            statuses=statuses,
            dry_run=not args.delete,
        )
    else:
        summary = prune_traces(
            args.trace_dir,
            max_age_seconds=args.max_age_days * 24 * 60 * 60,
            dry_run=not args.delete,
        )
    print(format_and_write_json(summary, args.output))
    if args.fail_on_errors and _trace_prune_has_errors(summary):
        raise SystemExit(1)


def _trace_prune_has_errors(summary: Dict[str, Any]) -> bool:
    errors = summary.get("errors")
    if isinstance(errors, list) and errors:
        return True
    return _summary_int(summary.get("unreadable")) > 0


def _summary_int(value: Any) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


if __name__ == "__main__":
    main()
