import hashlib
import json
import subprocess

from self_correcting_langgraph_agent.ops.release_manifest import (
    build_release_manifest,
    verify_release_manifest,
)


def test_build_release_manifest_records_artifact_hashes_and_sizes(tmp_path):
    artifact = tmp_path / "agent.whl"
    artifact.write_bytes(b"release-bytes")

    manifest = build_release_manifest([artifact])

    assert manifest["package"] == "self-correcting-langgraph-agent"
    assert manifest["version"] == "0.1.0"
    assert manifest["artifact_count"] == "1"
    assert manifest["artifacts"] == [
        {
            "path": str(artifact),
            "file_name": "agent.whl",
            "size_bytes": str(len(b"release-bytes")),
            "sha256": hashlib.sha256(b"release-bytes").hexdigest(),
        }
    ]


def test_release_manifest_cli_writes_json_manifest(tmp_path):
    artifact = tmp_path / "agent.whl"
    output = tmp_path / "manifest.json"
    artifact.write_bytes(b"cli-release-bytes")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            str(artifact),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout_payload = json.loads(completed.stdout)
    output_payload = json.loads(output.read_text())

    assert completed.stderr == ""
    assert stdout_payload == output_payload
    assert output_payload["artifacts"][0]["sha256"] == hashlib.sha256(
        b"cli-release-bytes"
    ).hexdigest()


def test_verify_release_manifest_reports_matching_artifacts(tmp_path):
    artifact = tmp_path / "agent.whl"
    manifest_path = tmp_path / "manifest.json"
    artifact.write_bytes(b"verified-release")
    manifest_path.write_text(json.dumps(build_release_manifest([artifact])))

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "verified",
        "artifact_count": "1",
        "checked": "1",
        "failures": [],
    }


def test_verify_release_manifest_reports_hash_mismatch(tmp_path):
    artifact = tmp_path / "agent.whl"
    manifest_path = tmp_path / "manifest.json"
    artifact.write_bytes(b"original-release")
    manifest_path.write_text(json.dumps(build_release_manifest([artifact])))
    artifact.write_bytes(b"tampered-release")

    report = verify_release_manifest(manifest_path)

    assert report["status"] == "failed"
    assert report["artifact_count"] == "1"
    assert report["checked"] == "1"
    assert report["failures"] == [
        {
            "path": str(artifact),
            "error": "sha256 mismatch",
        }
    ]


def test_verify_release_manifest_reports_artifact_count_mismatch(tmp_path):
    artifact = tmp_path / "agent.whl"
    manifest_path = tmp_path / "manifest.json"
    artifact.write_bytes(b"counted-release")
    manifest = build_release_manifest([artifact])
    manifest["artifact_count"] = "2"
    manifest_path.write_text(json.dumps(manifest))

    report = verify_release_manifest(manifest_path)

    assert report["status"] == "failed"
    assert report["artifact_count"] == "2"
    assert report["checked"] == "1"
    assert report["failures"] == [
        {
            "path": str(manifest_path),
            "error": "artifact_count mismatch",
        }
    ]


def test_verify_release_manifest_reports_package_and_version_mismatch(tmp_path):
    artifact = tmp_path / "agent.whl"
    manifest_path = tmp_path / "manifest.json"
    artifact.write_bytes(b"metadata-release")
    manifest = build_release_manifest([artifact])
    manifest["package"] = "other-package"
    manifest["version"] = "9.9.9"
    manifest_path.write_text(json.dumps(manifest))

    report = verify_release_manifest(manifest_path)

    assert report["status"] == "failed"
    assert report["artifact_count"] == "1"
    assert report["checked"] == "1"
    assert report["failures"] == [
        {
            "path": str(manifest_path),
            "error": "package mismatch",
        },
        {
            "path": str(manifest_path),
            "error": "version mismatch",
        },
    ]


def test_verify_release_manifest_reports_invalid_artifacts_schema(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": "self-correcting-langgraph-agent",
                "version": "0.1.0",
                "artifact_count": "1",
                "artifacts": "not-a-list",
            }
        )
    )

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "failed",
        "artifact_count": "1",
        "checked": "0",
        "failures": [
            {
                "path": str(manifest_path),
                "error": "artifacts must be a list",
            }
        ],
    }


def test_verify_release_manifest_reports_invalid_artifact_entry_schema(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": "self-correcting-langgraph-agent",
                "version": "0.1.0",
                "artifact_count": "1",
                "artifacts": ["not-an-object"],
            }
        )
    )

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "failed",
        "artifact_count": "1",
        "checked": "0",
        "failures": [
            {
                "path": str(manifest_path),
                "error": "artifact entry must be an object",
            }
        ],
    }


def test_verify_release_manifest_reports_missing_artifact_path(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": "self-correcting-langgraph-agent",
                "version": "0.1.0",
                "artifact_count": "1",
                "artifacts": [{"sha256": "abc", "size_bytes": "123"}],
            }
        )
    )

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "failed",
        "artifact_count": "1",
        "checked": "0",
        "failures": [
            {
                "path": str(manifest_path),
                "error": "artifact path missing",
            }
        ],
    }


def test_verify_release_manifest_reports_directory_artifact_path(tmp_path):
    artifact_dir = tmp_path / "dist"
    artifact_dir.mkdir()
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": "self-correcting-langgraph-agent",
                "version": "0.1.0",
                "artifact_count": "1",
                "artifacts": [
                    {
                        "path": str(artifact_dir),
                        "sha256": "abc",
                        "size_bytes": "123",
                    }
                ],
            }
        )
    )

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "failed",
        "artifact_count": "1",
        "checked": "1",
        "failures": [
            {
                "path": str(artifact_dir),
                "error": "artifact is not a file",
            }
        ],
    }


def test_verify_release_manifest_reports_invalid_artifact_path(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "package": "self-correcting-langgraph-agent",
                "version": "0.1.0",
                "artifact_count": "1",
                "artifacts": [
                    {
                        "path": "bad\u0000path",
                        "sha256": "abc",
                        "size_bytes": "123",
                    }
                ],
            }
        )
    )

    report = verify_release_manifest(manifest_path)

    assert report == {
        "status": "failed",
        "artifact_count": "1",
        "checked": "0",
        "failures": [
            {
                "path": str(manifest_path),
                "error": "artifact path invalid",
            }
        ],
    }


def test_release_manifest_cli_verify_exits_nonzero_for_mismatched_artifacts(tmp_path):
    artifact = tmp_path / "agent.whl"
    manifest_path = tmp_path / "manifest.json"
    artifact.write_bytes(b"original-release")
    manifest_path.write_text(json.dumps(build_release_manifest([artifact])))
    artifact.write_bytes(b"tampered-release")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            "--verify",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["status"] == "failed"


def test_release_manifest_cli_verify_reports_invalid_json_without_traceback(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not-json")

    completed = subprocess.run(
        [
            ".venv/bin/python",
            "-m",
            "self_correcting_langgraph_agent.ops.release_manifest",
            "--verify",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "invalid release manifest JSON" in completed.stderr
    assert "Traceback" not in completed.stderr
