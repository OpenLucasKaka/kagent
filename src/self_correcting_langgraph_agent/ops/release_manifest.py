from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from self_correcting_langgraph_agent import __version__

PACKAGE_NAME = "self-correcting-langgraph-agent"


def build_release_manifest(artifact_paths: Iterable[Path]) -> Dict[str, Any]:
    artifacts = [_artifact_record(Path(path)) for path in artifact_paths]
    return {
        "package": PACKAGE_NAME,
        "version": __version__,
        "artifact_count": str(len(artifacts)),
        "artifacts": artifacts,
    }


def verify_release_manifest(manifest_path: Path) -> Dict[str, Any]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    artifacts = manifest.get("artifacts", [])
    failures = []
    checked = 0
    if not isinstance(artifacts, list):
        declared_artifact_count = str(manifest.get("artifact_count", "0"))
        return {
            "status": "failed",
            "artifact_count": declared_artifact_count,
            "checked": "0",
            "failures": [
                {
                    "path": str(manifest_path),
                    "error": "artifacts must be a list",
                }
            ],
        }
    if str(manifest.get("package", "")) != PACKAGE_NAME:
        failures.append({"path": str(manifest_path), "error": "package mismatch"})
    if str(manifest.get("version", "")) != __version__:
        failures.append({"path": str(manifest_path), "error": "version mismatch"})
    declared_artifact_count = str(manifest.get("artifact_count", len(artifacts)))
    if declared_artifact_count != str(len(artifacts)):
        failures.append(
            {
                "path": str(manifest_path),
                "error": "artifact_count mismatch",
            }
        )
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            failures.append(
                {
                    "path": str(manifest_path),
                    "error": "artifact entry must be an object",
                }
            )
            continue
        raw_path = artifact.get("path")
        if raw_path is None or str(raw_path).strip() == "":
            failures.append(
                {
                    "path": str(manifest_path),
                    "error": "artifact path missing",
                }
            )
            continue
        path_text = str(raw_path)
        if "\x00" in path_text:
            failures.append(
                {
                    "path": str(manifest_path),
                    "error": "artifact path invalid",
                }
            )
            continue
        path = Path(path_text)
        checked += 1
        if not path.exists():
            failures.append({"path": str(path), "error": "artifact missing"})
            continue
        if not path.is_file():
            failures.append({"path": str(path), "error": "artifact is not a file"})
            continue
        actual = _artifact_record(path)
        if actual["sha256"] != str(artifact.get("sha256", "")):
            failures.append({"path": str(path), "error": "sha256 mismatch"})
            continue
        if actual["size_bytes"] != str(artifact.get("size_bytes", "")):
            failures.append({"path": str(path), "error": "size mismatch"})
    return {
        "status": "failed" if failures else "verified",
        "artifact_count": declared_artifact_count,
        "checked": str(checked),
        "failures": failures,
    }


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate a JSON release manifest with artifact sha256 hashes."
    )
    parser.add_argument("artifacts", nargs="*", help="Artifact file paths to include.")
    parser.add_argument("--output", default="", metavar="PATH", help="Write manifest JSON to PATH.")
    parser.add_argument("--verify", default="", metavar="PATH", help="Verify an existing manifest.")
    args = parser.parse_args(argv)

    try:
        if args.verify:
            manifest = verify_release_manifest(Path(args.verify))
        else:
            if not args.artifacts:
                parser.error("at least one artifact path is required")
            manifest = build_release_manifest([Path(path) for path in args.artifacts])
        payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        if args.output:
            Path(args.output).write_text(payload, encoding="utf-8")
    except json.JSONDecodeError as exc:
        parser.error(f"invalid release manifest JSON: {exc}")
    except OSError as exc:
        parser.error(str(exc))
    print(payload, end="")
    if args.verify and manifest["status"] != "verified":
        raise SystemExit(1)


def _artifact_record(path: Path) -> Dict[str, str]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "file_name": path.name,
        "size_bytes": str(len(data)),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


if __name__ == "__main__":
    main()
