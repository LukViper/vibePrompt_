"""SQLite-backed project repository with a clear abstraction boundary."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Protocol

from app.persistence.schema import apply_schema
from app.projects.models import ProjectState, ProjectSummary


class ProjectRepository(Protocol):
    def create(self, project: ProjectState, *, owner_id: str | None = None) -> ProjectState: ...

    def get(self, project_id: str) -> ProjectState | None: ...

    def save(self, project: ProjectState) -> ProjectState: ...

    def list_summaries(self, *, owner_id: str | None = None) -> list[ProjectSummary]: ...

    def delete(self, project_id: str) -> bool: ...

    def get_owner(self, project_id: str) -> str | None: ...


class InMemoryProjectRepository:
    """Useful for tests; isolates projects by id."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectState] = {}
        self._owners: dict[str, str | None] = {}
        self._lock = Lock()

    def create(self, project: ProjectState, *, owner_id: str | None = None) -> ProjectState:
        with self._lock:
            self._projects[project.id] = project.model_copy(deep=True)
            self._owners[project.id] = owner_id
            return project.model_copy(deep=True)

    def get(self, project_id: str) -> ProjectState | None:
        with self._lock:
            project = self._projects.get(project_id)
            return project.model_copy(deep=True) if project else None

    def save(self, project: ProjectState) -> ProjectState:
        with self._lock:
            if project.id not in self._projects:
                raise KeyError(f"Project {project.id} not found")
            project.touch()
            self._projects[project.id] = project.model_copy(deep=True)
            return project.model_copy(deep=True)

    def list_summaries(self, *, owner_id: str | None = None) -> list[ProjectSummary]:
        with self._lock:
            projects = list(self._projects.values())
            if owner_id is not None:
                projects = [
                    p for p in projects if self._owners.get(p.id) == owner_id
                ]
            return [
                ProjectSummary(
                    id=p.id,
                    name=p.name,
                    objective=p.objective,
                    open_finding_count=len(p.open_findings()),
                    message_count=len(p.messages),
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
                for p in sorted(projects, key=lambda x: x.updated_at, reverse=True)
            ]

    def delete(self, project_id: str) -> bool:
        with self._lock:
            self._owners.pop(project_id, None)
            return self._projects.pop(project_id, None) is not None

    def get_owner(self, project_id: str) -> str | None:
        with self._lock:
            return self._owners.get(project_id)


class SQLiteProjectRepository:
    """Local SQLite persistence. Swap later for Postgres without changing callers."""

    def __init__(self, database_path: str) -> None:
        self.path = Path(database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            apply_schema(conn)

    def create(self, project: ProjectState, *, owner_id: str | None = None) -> ProjectState:
        payload = project.model_dump_json()
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "owner_id" in cols:
                conn.execute(
                    """
                    INSERT INTO projects (id, name, data, created_at, updated_at, owner_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project.id,
                        project.name,
                        payload,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                        owner_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO projects (id, name, data, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        project.id,
                        project.name,
                        payload,
                        project.created_at.isoformat(),
                        project.updated_at.isoformat(),
                    ),
                )
            conn.commit()
        return project

    def get(self, project_id: str) -> ProjectState | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT data FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        if not row:
            return None
        return ProjectState.model_validate_json(row["data"])

    def save(self, project: ProjectState) -> ProjectState:
        project.touch()
        payload = project.model_dump_json()
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE projects SET name = ?, data = ?, updated_at = ? WHERE id = ?",
                (project.name, payload, project.updated_at.isoformat(), project.id),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Project {project.id} not found")
            conn.commit()
        return project

    def list_summaries(self, *, owner_id: str | None = None) -> list[ProjectSummary]:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if owner_id is not None and "owner_id" in cols:
                rows = conn.execute(
                    """
                    SELECT data FROM projects
                    WHERE owner_id = ?
                    ORDER BY updated_at DESC
                    """,
                    (owner_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data FROM projects ORDER BY updated_at DESC"
                ).fetchall()
        summaries: list[ProjectSummary] = []
        for row in rows:
            p = ProjectState.model_validate_json(row["data"])
            summaries.append(
                ProjectSummary(
                    id=p.id,
                    name=p.name,
                    objective=p.objective,
                    open_finding_count=len(p.open_findings()),
                    message_count=len(p.messages),
                    created_at=p.created_at,
                    updated_at=p.updated_at,
                )
            )
        return summaries

    def delete(self, project_id: str) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_owner(self, project_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "owner_id" not in cols:
                return None
            row = conn.execute(
                "SELECT owner_id FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        return row["owner_id"]


def dump_project_snapshot(project: ProjectState) -> dict:
    """Compact snapshot for prompts — never includes secrets."""
    return json.loads(
        project.model_dump_json(
            exclude={"messages": {"__all__": {"metadata"}}},
        )
    )
