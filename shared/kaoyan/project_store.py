"""Authorization-aware draft/project storage with append-only audit events."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class RevisionConflict(RuntimeError):
    """A project changed after the caller loaded it."""


class ProjectStore:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root.resolve()
        self.tmp_root = self.repo_root / "tmp" / "question-builder" / "sessions"
        self.saved_root = self.repo_root / "projects" / "question-builder"
        self._lock = threading.RLock()
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        ttl_hours = float(os.environ.get("KAOYAN_SESSION_TTL_HOURS", "24"))
        if ttl_hours < 0:
            raise ValueError("KAOYAN_SESSION_TTL_HOURS must be zero or greater")
        if ttl_hours:
            self.cleanup_expired(ttl_hours)

    def create(self, initial: dict[str, Any]) -> dict[str, Any]:
        project_id = uuid.uuid4().hex[:12]
        project = {
            **initial,
            "schema_version": "1.0",
            "project_id": project_id,
            "revision": 0,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "retention": {"status": "session_only", "keep_final_pdf": True, "authorized_at": None},
            "events": [],
        }
        (self.tmp_root / project_id).mkdir(parents=True)
        self.write(project, event_type="project_created", details={"scope": "session_only"})
        return project

    def find_dir(self, project_id: str) -> Path:
        self._safe_id(project_id)
        for root in (self.tmp_root, self.saved_root):
            candidate = root / project_id
            if candidate.is_dir():
                return candidate
        raise FileNotFoundError(f"Project not found: {project_id}")

    def load(self, project_id: str, expected_revision: int | None = None) -> dict[str, Any]:
        with self._lock:
            project = json.loads((self.find_dir(project_id) / "project.json").read_text(encoding="utf-8"))
            project.setdefault("revision", 1)
            if expected_revision is not None and project.get("revision") != expected_revision:
                raise RevisionConflict(
                    f"Project revision conflict: expected {expected_revision}, current {project.get('revision')}"
                )
            return project

    def write(
        self,
        project: dict[str, Any],
        event_type: str | None = None,
        details: dict[str, Any] | None = None,
        expected_revision: int | None = None,
    ) -> None:
        project_id = self._safe_id(str(project["project_id"]))
        with self._lock:
            folder = self.find_dir(project_id)
            target = folder / "project.json"
            current_revision = 0
            if target.is_file():
                persisted = json.loads(target.read_text(encoding="utf-8"))
                current_revision = int(persisted.get("revision", 1))
            supplied_revision = project.get("revision") if expected_revision is None else expected_revision
            if supplied_revision != current_revision:
                raise RevisionConflict(
                    f"Project revision conflict: expected {supplied_revision}, current {current_revision}"
                )
            if event_type:
                project.setdefault("events", []).append({"at": utc_now(), "type": event_type, "details": details or {}})
            project["revision"] = current_revision + 1
            project["updated_at"] = utc_now()
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=folder, delete=False, suffix=".tmp") as stream:
                json.dump(project, stream, ensure_ascii=False, indent=2)
                temp_path = Path(stream.name)
            temp_path.replace(target)

    def list_projects(self) -> list[dict[str, Any]]:
        projects = []
        for status, root in (("session_only", self.tmp_root), ("keep_project", self.saved_root)):
            if not root.is_dir():
                continue
            for path in root.glob("*/project.json"):
                try:
                    item = json.loads(path.read_text(encoding="utf-8"))
                    projects.append({
                        "project_id": item["project_id"], "title": item.get("title", "未命名题集"),
                        "updated_at": item.get("updated_at"), "retention": status,
                    })
                except (OSError, json.JSONDecodeError, KeyError):
                    continue
        return sorted(projects, key=lambda item: item.get("updated_at") or "", reverse=True)

    def authorize_retention(
        self,
        project_id: str,
        status: str,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if status not in {"keep_project", "final_pdf_only", "discard_all"}:
            raise ValueError("Unknown retention choice")
        with self._lock:
            project = self.load(project_id, expected_revision)
            source = self.find_dir(project_id)
            if status == "keep_project":
                self.saved_root.mkdir(parents=True, exist_ok=True)
                target = self.saved_root / project_id
                if source != target and target.exists():
                    raise FileExistsError(f"Retained project already exists: {project_id}")
                project["retention"] = {"status": status, "keep_final_pdf": True, "authorized_at": utc_now()}
                self.write(project, "retention_authorized", {"choice": status})
                if source != target:
                    shutil.move(str(source), str(target))
                return project

            if status == "discard_all":
                shutil.rmtree(source)
                return {"project_id": project_id, "retention": {"status": status}, "kept_files": []}

            exports = source / "exports"
            pdfs = sorted(path for path in exports.glob("*.pdf") if path.is_file() and not path.is_symlink()) if exports.is_dir() else []
            if not pdfs:
                raise ValueError("final_pdf_only requires at least one exported PDF")

            output_root = self.repo_root / "outputs" / "question-builder"
            output_root.mkdir(parents=True, exist_ok=True)
            target = output_root / project_id
            if target.exists():
                raise FileExistsError(f"Final PDF output already exists: {project_id}")
            staging = Path(tempfile.mkdtemp(prefix=f".{project_id}-", dir=output_root))
            try:
                for path in pdfs:
                    staged = staging / path.name
                    shutil.copy2(path, staged)
                    if (
                        not staged.is_file()
                        or staged.stat().st_size <= 0
                        or staged.stat().st_size != path.stat().st_size
                    ):
                        raise OSError(f"Failed to stage final PDF: {path.name}")
                staging.replace(target)
            except Exception:
                if staging.exists():
                    shutil.rmtree(staging)
                raise

            shutil.rmtree(source)
            return {
                "project_id": project_id,
                "retention": {"status": status},
                "kept_files": [path.name for path in pdfs],
            }

    def cleanup_expired(self, max_age_hours: float) -> list[str]:
        if max_age_hours <= 0:
            raise ValueError("max_age_hours must be greater than zero")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        removed: list[str] = []
        with self._lock:
            for folder in self.tmp_root.iterdir():
                project_file = folder / "project.json"
                if not folder.is_dir() or not project_file.is_file():
                    continue
                try:
                    project = json.loads(project_file.read_text(encoding="utf-8"))
                    updated = datetime.fromisoformat(str(project["updated_at"]))
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                except (OSError, ValueError, KeyError, json.JSONDecodeError):
                    continue
                if updated >= cutoff:
                    continue
                try:
                    shutil.rmtree(folder)
                except OSError:
                    continue
                removed.append(folder.name)
        return removed

    @staticmethod
    def _safe_id(project_id: str) -> str:
        if not project_id or not project_id.replace("-", "").isalnum():
            raise ValueError("Invalid project ID")
        return project_id
