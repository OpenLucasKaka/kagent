import json

import pytest

from kagent.runtime import checkpoint_storage, patch_checkpoints
from kagent.runtime.file_transaction import capture_text_states
from kagent.runtime.patch_checkpoints import (
    PatchCheckpointStore,
    commit_checkpointed_text_changes,
)


def test_patch_checkpoint_store_persists_owner_only_history_without_content(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    store = PatchCheckpointStore(tmp_path / "state")
    before = capture_text_states([target])

    checkpoint_id = store.prepare(
        workspace,
        before,
        {target: "after\n"},
    )
    store.mark_committed(workspace, checkpoint_id)

    history = store.history(workspace)
    assert history == {
        "checkpoints": [
            {
                "checkpoint_id": checkpoint_id,
                "created_at": history["checkpoints"][0]["created_at"],
                "file_count": 1,
                "paths": ["notes.md"],
            }
        ],
        "checkpoint_count": 1,
    }
    serialized_history = json.dumps(history)
    assert "before" not in serialized_history
    assert "after" not in serialized_history

    checkpoint_directory = next((tmp_path / "state").glob("*/checkpoints/*"))
    assert checkpoint_directory.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in checkpoint_directory.iterdir())


def test_patch_checkpoint_store_loads_revert_state_and_rejects_tampering(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    existing = workspace / "existing.md"
    existing.write_text("before\n", encoding="utf-8")
    added = workspace / "added.md"
    store = PatchCheckpointStore(tmp_path / "state")
    before = capture_text_states([existing, added])

    checkpoint_id = store.prepare(
        workspace,
        before,
        {existing: "after\n", added: "new\n"},
    )
    store.mark_committed(workspace, checkpoint_id)

    revert = store.load_revert(workspace, checkpoint_id)
    assert revert.expected_current == {existing: "after\n", added: "new\n"}
    assert revert.staged_contents == {existing: "before\n", added: None}

    checkpoint_directory = next((tmp_path / "state").glob("*/checkpoints/*"))
    before_blob = next(checkpoint_directory.glob("before-*.txt"))
    before_blob.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint content SHA-256 mismatch"):
        store.load_revert(workspace, checkpoint_id)


def test_patch_checkpoint_store_rejects_symlink_state_root(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    real_state = tmp_path / "real-state"
    real_state.mkdir()
    state_link = tmp_path / "state-link"
    state_link.symlink_to(real_state, target_is_directory=True)
    store = PatchCheckpointStore(state_link)

    with pytest.raises(ValueError, match="must not contain symlinks"):
        store.prepare(
            workspace,
            capture_text_states([target]),
            {target: "after\n"},
        )


def test_patch_checkpoint_store_rejects_manifest_path_escape(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    store = PatchCheckpointStore(tmp_path / "state")
    checkpoint_id = store.prepare(
        workspace,
        capture_text_states([target]),
        {target: "after\n"},
    )
    store.mark_committed(workspace, checkpoint_id)
    checkpoint_directory = next((tmp_path / "state").glob("*/checkpoints/*"))
    manifest_path = checkpoint_directory / "manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = envelope["manifest"]
    manifest["entries"][0]["path"] = "../outside.md"
    key = checkpoint_storage.load_or_create_signing_key(tmp_path / "state")
    manifest_path.write_text(
        json.dumps(checkpoint_storage.signed_manifest_payload(manifest, key)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="must stay inside the workspace"):
        store.load_revert(workspace, checkpoint_id)


def test_checkpoint_commit_restores_files_when_manifest_commit_fails(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    store = PatchCheckpointStore(tmp_path / "state")

    def fail_mark_committed(_workspace_root, _checkpoint_id):
        raise OSError("injected manifest failure")

    monkeypatch.setattr(store, "mark_committed", fail_mark_committed)

    with pytest.raises(OSError, match="injected manifest failure"):
        commit_checkpointed_text_changes(
            store,
            workspace,
            {target: "after\n"},
        )

    assert target.read_text(encoding="utf-8") == "before\n"
    assert store.history(workspace) == {"checkpoints": [], "checkpoint_count": 0}


@pytest.mark.parametrize("checkpoint_id", ["..", ".", "../escape", "missing"])
def test_patch_checkpoint_store_rejects_invalid_checkpoint_ids(
    tmp_path,
    checkpoint_id,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = PatchCheckpointStore(tmp_path / "state")

    with pytest.raises(ValueError, match="invalid checkpoint_id"):
        store.load_revert(workspace, checkpoint_id)


def test_patch_checkpoint_store_cleans_prepared_blobs_when_manifest_write_fails(
    tmp_path,
    monkeypatch,
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    state_root = tmp_path / "state"
    store = PatchCheckpointStore(state_root)

    def fail_manifest(_target, _payload, _state_root):
        raise OSError("injected manifest failure")

    monkeypatch.setattr(patch_checkpoints, "write_signed_manifest", fail_manifest)

    with pytest.raises(OSError, match="injected manifest failure"):
        store.prepare(
            workspace,
            capture_text_states([target]),
            {target: "after\n"},
        )

    assert not list(state_root.glob("*/checkpoints/*"))


def test_patch_checkpoint_store_recovers_partial_prepared_commit(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    first = workspace / "first.md"
    second = workspace / "second.md"
    first.write_text("first before\n", encoding="utf-8")
    second.write_text("second before\n", encoding="utf-8")
    store = PatchCheckpointStore(tmp_path / "state")
    before = capture_text_states([first, second])
    store.prepare(
        workspace,
        before,
        {first: "first after\n", second: "second after\n"},
    )
    first.write_text("first after\n", encoding="utf-8")

    recovered = store.recover_prepared(workspace)

    assert recovered == 1
    assert first.read_text(encoding="utf-8") == "first before\n"
    assert second.read_text(encoding="utf-8") == "second before\n"
    assert store.history(workspace) == {"checkpoints": [], "checkpoint_count": 0}


def test_patch_checkpoint_store_does_not_overwrite_diverged_recovery_file(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    store = PatchCheckpointStore(tmp_path / "state")
    store.prepare(
        workspace,
        capture_text_states([target]),
        {target: "after\n"},
    )
    target.write_text("user edit\n", encoding="utf-8")

    with pytest.raises(ValueError, match="recovery SHA-256 conflict"):
        store.recover_prepared(workspace)

    assert target.read_text(encoding="utf-8") == "user edit\n"


def test_patch_checkpoint_store_rejects_joint_manifest_and_blob_tampering(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "notes.md"
    target.write_text("before\n", encoding="utf-8")
    state_root = tmp_path / "state"
    store = PatchCheckpointStore(state_root)
    checkpoint_id = store.prepare(
        workspace,
        capture_text_states([target]),
        {target: "after\n"},
    )
    store.mark_committed(workspace, checkpoint_id)
    checkpoint_directory = next(state_root.glob("*/checkpoints/*"))
    before_blob = next(checkpoint_directory.glob("before-*.txt"))
    before_blob.write_text("forged\n", encoding="utf-8")
    manifest_path = checkpoint_directory / "manifest.json"
    envelope = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope["manifest"]["entries"][0]["before"]["sha256"] = (
        patch_checkpoints.hashlib.sha256(b"forged\n").hexdigest()
    )
    manifest_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ValueError, match="checkpoint manifest integrity check failed"):
        store.load_revert(workspace, checkpoint_id)
