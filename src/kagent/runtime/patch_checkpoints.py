from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kagent.runtime.checkpoint_storage import (
    FILE_MODE,
    MANIFEST_VERSION,
    atomic_write_text,
    ensure_store_layout,
    new_checkpoint_id,
    read_signed_manifest,
    reject_existing_symlink_chain,
    reject_symlink,
    remove_checkpoint_directory,
    resolve_checkpoint_target,
    validate_checkpoint_id,
    write_signed_manifest,
)
from kagent.runtime.file_transaction import (
    TextFileState,
    capture_text_states,
    commit_text_changes,
    validate_workspace_targets,
    workspace_transaction,
)


@dataclass(frozen=True)
class PatchRevert:
    checkpoint_id: str
    expected_current: dict[Path, str | None]
    staged_contents: dict[Path, str | None]
    target_modes: dict[Path, int]


class PatchCheckpointStore:
    def __init__(self, state_root: str | Path) -> None:
        self.state_root = Path(state_root).expanduser()

    @classmethod
    def from_environment(cls) -> "PatchCheckpointStore":
        configured = os.environ.get("KAGENT_PATCH_STATE_DIR", "").strip()
        if configured:
            return cls(configured)
        state_home = os.environ.get("XDG_STATE_HOME", "").strip()
        root = Path(state_home).expanduser() if state_home else Path.home() / ".local/state"
        return cls(root / "kagent" / "patches")

    def prepare(
        self,
        workspace_root: Path,
        before: dict[Path, TextFileState],
        after: dict[Path, str | None],
    ) -> str:
        if set(before) != set(after):
            raise ValueError("checkpoint before and after paths must match")
        workspace_root = workspace_root.resolve()
        checkpoint_id = new_checkpoint_id()
        checkpoint_directory = self._checkpoint_directory(
            workspace_root,
            checkpoint_id,
        )
        ensure_store_layout(
            self.state_root,
            self._workspace_directory(workspace_root),
            checkpoint_directory,
        )
        try:
            entries = []
            for index, target in enumerate(after):
                relative_path = target.relative_to(workspace_root).as_posix()
                before_state = before[target]
                after_content = after[target]
                entries.append(
                    {
                        "path": relative_path,
                        "before": self._write_state(
                            checkpoint_directory,
                            f"before-{index:04d}.txt",
                            before_state.content,
                            before_state.mode,
                        ),
                        "after": self._write_state(
                            checkpoint_directory,
                            f"after-{index:04d}.txt",
                            after_content,
                            before_state.mode
                            if before_state.content is not None
                            else FILE_MODE,
                        ),
                    }
                )
            manifest = {
                "version": MANIFEST_VERSION,
                "checkpoint_id": checkpoint_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "prepared",
                "entries": entries,
            }
            self._write_manifest(checkpoint_directory, manifest)
        except Exception:
            remove_checkpoint_directory(checkpoint_directory)
            raise
        return checkpoint_id

    def mark_committed(self, workspace_root: Path, checkpoint_id: str) -> None:
        checkpoint_directory, manifest = self._load_manifest(
            workspace_root,
            checkpoint_id,
        )
        if manifest.get("status") != "prepared":
            raise ValueError("checkpoint is not prepared")
        manifest["status"] = "committed"
        self._write_manifest(checkpoint_directory, manifest)

    def discard(self, workspace_root: Path, checkpoint_id: str) -> None:
        checkpoint_directory = self._checkpoint_directory(
            workspace_root.resolve(),
            checkpoint_id,
        )
        if not checkpoint_directory.exists():
            return
        remove_checkpoint_directory(checkpoint_directory)

    def history(self, workspace_root: Path, *, limit: int = 20) -> dict[str, Any]:
        if limit < 1:
            raise ValueError("limit must be positive")
        reject_existing_symlink_chain(self.state_root)
        checkpoints_directory = (
            self._workspace_directory(workspace_root.resolve()) / "checkpoints"
        )
        if not checkpoints_directory.exists():
            return {"checkpoints": [], "checkpoint_count": 0}
        reject_symlink(checkpoints_directory)
        checkpoints = []
        for directory in sorted(checkpoints_directory.iterdir(), reverse=True):
            if len(checkpoints) >= limit:
                break
            if directory.is_symlink() or not directory.is_dir():
                continue
            try:
                _, manifest = self._load_manifest(workspace_root, directory.name)
            except ValueError:
                continue
            if manifest.get("status") != "committed":
                continue
            entries = manifest["entries"]
            checkpoints.append(
                {
                    "checkpoint_id": manifest["checkpoint_id"],
                    "created_at": manifest["created_at"],
                    "file_count": len(entries),
                    "paths": [entry["path"] for entry in entries],
                }
            )
        return {"checkpoints": checkpoints, "checkpoint_count": len(checkpoints)}

    def load_revert(self, workspace_root: Path, checkpoint_id: str) -> PatchRevert:
        workspace_root = workspace_root.resolve()
        checkpoint_directory, manifest = self._load_manifest(
            workspace_root,
            checkpoint_id,
        )
        if manifest.get("status") != "committed":
            raise ValueError("checkpoint is not committed")
        return self._revert_from_manifest(
            workspace_root,
            checkpoint_directory,
            manifest,
        )

    def recover_prepared(self, workspace_root: Path) -> int:
        workspace_root = workspace_root.resolve()
        checkpoints_directory = self._workspace_directory(workspace_root) / "checkpoints"
        if not checkpoints_directory.exists():
            return 0
        recovered = 0
        with workspace_transaction(workspace_root):
            for directory in sorted(checkpoints_directory.iterdir()):
                if directory.is_symlink() or not directory.is_dir():
                    continue
                _, manifest = self._load_manifest(workspace_root, directory.name)
                if manifest.get("status") != "prepared":
                    continue
                revert = self._revert_from_manifest(
                    workspace_root,
                    directory,
                    manifest,
                )
                validate_workspace_targets(workspace_root, revert.staged_contents)
                current_states = capture_text_states(revert.staged_contents)
                for target, current_state in current_states.items():
                    allowed_contents = {
                        revert.expected_current[target],
                        revert.staged_contents[target],
                    }
                    if current_state.content not in allowed_contents:
                        relative_path = target.relative_to(workspace_root).as_posix()
                        raise ValueError(
                            f"checkpoint recovery SHA-256 conflict: {relative_path}"
                        )
                if any(
                    current_states[target].content != revert.staged_contents[target]
                    for target in revert.staged_contents
                ):
                    commit_text_changes(
                        workspace_root,
                        revert.staged_contents,
                        original_states=current_states,
                        target_modes=revert.target_modes,
                    )
                self.discard(workspace_root, directory.name)
                recovered += 1
        return recovered

    def _revert_from_manifest(
        self,
        workspace_root: Path,
        checkpoint_directory: Path,
        manifest: dict[str, Any],
    ) -> PatchRevert:
        expected_current = {}
        staged_contents = {}
        target_modes = {}
        for entry in manifest["entries"]:
            target = resolve_checkpoint_target(workspace_root, entry["path"])
            expected_current[target] = self._read_state(
                checkpoint_directory,
                entry["after"],
            )
            staged_contents[target] = self._read_state(
                checkpoint_directory,
                entry["before"],
            )
            target_modes[target] = int(entry["before"]["mode"])
        return PatchRevert(
            checkpoint_id=manifest["checkpoint_id"],
            expected_current=expected_current,
            staged_contents=staged_contents,
            target_modes=target_modes,
        )

    def _workspace_directory(self, workspace_root: Path) -> Path:
        identity = hashlib.sha256(str(workspace_root).encode("utf-8")).hexdigest()
        return self.state_root / identity

    def _checkpoint_directory(
        self,
        workspace_root: Path,
        checkpoint_id: str,
    ) -> Path:
        validate_checkpoint_id(checkpoint_id)
        return self._workspace_directory(workspace_root) / "checkpoints" / checkpoint_id

    def _load_manifest(
        self,
        workspace_root: Path,
        checkpoint_id: str,
    ) -> tuple[Path, dict[str, Any]]:
        checkpoint_directory = self._checkpoint_directory(
            workspace_root.resolve(),
            checkpoint_id,
        )
        reject_existing_symlink_chain(self.state_root)
        manifest_path = checkpoint_directory / "manifest.json"
        reject_symlink(checkpoint_directory)
        reject_symlink(manifest_path)
        if not manifest_path.is_file():
            raise ValueError("checkpoint does not exist")
        manifest = read_signed_manifest(
            manifest_path,
            self.state_root,
            checkpoint_id,
        )
        return checkpoint_directory, manifest

    def _write_manifest(
        self,
        checkpoint_directory: Path,
        manifest: dict[str, Any],
    ) -> None:
        write_signed_manifest(
            checkpoint_directory / "manifest.json",
            manifest,
            self.state_root,
        )

    def _write_state(
        self,
        checkpoint_directory: Path,
        blob_name: str,
        content: str | None,
        mode: int,
    ) -> dict[str, Any]:
        if content is None:
            return {"exists": False, "sha256": "", "mode": mode, "blob": ""}
        encoded = content.encode("utf-8")
        atomic_write_text(checkpoint_directory / blob_name, content)
        return {
            "exists": True,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "mode": mode,
            "blob": blob_name,
        }

    def _read_state(
        self,
        checkpoint_directory: Path,
        state: Any,
    ) -> str | None:
        if not isinstance(state, dict) or not isinstance(state.get("exists"), bool):
            raise ValueError("checkpoint manifest is invalid")
        if state["exists"] is False:
            return None
        blob_name = state.get("blob")
        expected_sha256 = state.get("sha256")
        if not isinstance(blob_name, str) or Path(blob_name).name != blob_name:
            raise ValueError("checkpoint manifest is invalid")
        blob_path = checkpoint_directory / blob_name
        reject_symlink(blob_path)
        if not blob_path.is_file():
            raise ValueError("checkpoint content is missing")
        content = blob_path.read_text(encoding="utf-8")
        actual_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if actual_sha256 != expected_sha256:
            raise ValueError("checkpoint content SHA-256 mismatch")
        return content


def commit_checkpointed_text_changes(
    store: PatchCheckpointStore,
    workspace_root: Path,
    staged_contents: dict[Path, str | None],
    *,
    target_modes: dict[Path, int] | None = None,
) -> str:
    original_states = capture_text_states(staged_contents)
    checkpoint_id = store.prepare(workspace_root, original_states, staged_contents)
    files_committed = False
    try:
        commit_text_changes(
            workspace_root,
            staged_contents,
            original_states=original_states,
            target_modes=target_modes,
        )
        files_committed = True
        store.mark_committed(workspace_root, checkpoint_id)
    except Exception as commit_error:
        rollback_error = None
        if files_committed:
            try:
                commit_text_changes(
                    workspace_root,
                    {
                        target: state.content
                        for target, state in original_states.items()
                    },
                    target_modes={
                        target: state.mode for target, state in original_states.items()
                    },
                )
            except Exception as exc:
                rollback_error = exc
        try:
            store.discard(workspace_root, checkpoint_id)
        except Exception as discard_error:
            if rollback_error is None:
                rollback_error = discard_error
        if rollback_error is not None:
            raise RuntimeError(
                f"checkpoint commit failed: {commit_error}; "
                f"rollback failed: {rollback_error}"
            ) from commit_error
        raise
    return checkpoint_id
