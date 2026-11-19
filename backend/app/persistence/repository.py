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
    def create(
        self,
        project: ProjectState,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> ProjectState: ...

    def get(self, project_id: str, *, org_id: str | None = None) -> ProjectState | None: ...

    def save(self, project: ProjectState, *, org_id: str | None = None) -> ProjectState: ...

    def list_summaries(
        self,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> list[ProjectSummary]: ...

    def delete(self, project_id: str, *, org_id: str | None = None, soft: bool = True) -> bool: ...

    def get_owner(self, project_id: str) -> str | None: ...

    def get_org_id(self, project_id: str) -> str | None: ...


class InMemoryProjectRepository:
    """Useful for tests; isolates projects by id."""

    def __init__(self) -> None:
        self._projects: dict[str, ProjectState] = {}
        self._owners: dict[str, str | None] = {}
        self._orgs: dict[str, str | None] = {}
        self._deleted: set[str] = set()
        self._lock = Lock()

    def create(
        self,
        project: ProjectState,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> ProjectState:
        with self._lock:
            self._projects[project.id] = project.model_copy(deep=True)
            self._owners[project.id] = owner_id
            self._orgs[project.id] = org_id
            self._deleted.discard(project.id)
            return project.model_copy(deep=True)

    def get(self, project_id: str, *, org_id: str | None = None) -> ProjectState | None:
        with self._lock:
            if project_id in self._deleted:
                return None
            if org_id is not None and self._orgs.get(project_id) not in (org_id, None):
                return None
            project = self._projects.get(project_id)
            return project.model_copy(deep=True) if project else None

    def save(self, project: ProjectState, *, org_id: str | None = None) -> ProjectState:
        with self._lock:
            if project.id not in self._projects or project.id in self._deleted:
                raise KeyError(f"Project {project.id} not found")
            if org_id is not None and self._orgs.get(project.id) not in (org_id, None):
                raise KeyError(f"Project {project.id} not found")
            project.touch()
            self._projects[project.id] = project.model_copy(deep=True)
            return project.model_copy(deep=True)

    def list_summaries(
        self,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> list[ProjectSummary]:
        with self._lock:
            projects = [
                p
                for p in self._projects.values()
                if p.id not in self._deleted
            ]
            if org_id is not None:
                projects = [p for p in projects if self._orgs.get(p.id) == org_id]
            elif owner_id is not None:
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

    def delete(self, project_id: str, *, org_id: str | None = None, soft: bool = True) -> bool:
        with self._lock:
            if project_id not in self._projects:
                return False
            if org_id is not None and self._orgs.get(project_id) not in (org_id, None):
                return False
            if soft:
                self._deleted.add(project_id)
                return True
            self._owners.pop(project_id, None)
            self._orgs.pop(project_id, None)
            self._deleted.discard(project_id)
            return self._projects.pop(project_id, None) is not None

    def get_owner(self, project_id: str) -> str | None:
        with self._lock:
            return self._owners.get(project_id)

    def get_org_id(self, project_id: str) -> str | None:
        with self._lock:
            return self._orgs.get(project_id)


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

    def create(
        self,
        project: ProjectState,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> ProjectState:
        payload = project.model_dump_json()
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            fields = ["id", "name", "data", "created_at", "updated_at"]
            values: list[object] = [
                project.id,
                project.name,
                payload,
                project.created_at.isoformat(),
                project.updated_at.isoformat(),
            ]
            if "owner_id" in cols:
                fields.append("owner_id")
                values.append(owner_id)
            if "org_id" in cols:
                fields.append("org_id")
                values.append(org_id)
            placeholders = ", ".join("?" for _ in fields)
            conn.execute(
                f"INSERT INTO projects ({', '.join(fields)}) VALUES ({placeholders})",
                tuple(values),
            )
            conn.commit()
        return project

    def get(self, project_id: str, *, org_id: str | None = None) -> ProjectState | None:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            clauses = ["id = ?"]
            params: list[object] = [project_id]
            if "deleted_at" in cols:
                clauses.append("deleted_at IS NULL")
            if org_id is not None and "org_id" in cols:
                clauses.append("org_id = ?")
                params.append(org_id)
            row = conn.execute(
                f"SELECT data FROM projects WHERE {' AND '.join(clauses)}",
                tuple(params),
            ).fetchone()
        if not row:
            return None
        return ProjectState.model_validate_json(row["data"])

    def save(self, project: ProjectState, *, org_id: str | None = None) -> ProjectState:
        project.touch()
        payload = project.model_dump_json()
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            clauses = ["id = ?"]
            where_params: list[object] = [project.id]
            if "deleted_at" in cols:
                clauses.append("deleted_at IS NULL")
            if org_id is not None and "org_id" in cols:
                clauses.append("org_id = ?")
                where_params.append(org_id)
            cur = conn.execute(
                f"UPDATE projects SET name = ?, data = ?, updated_at = ? WHERE {' AND '.join(clauses)}",
                (
                    project.name,
                    payload,
                    project.updated_at.isoformat(),
                    *where_params,
                ),
            )
            if cur.rowcount == 0:
                raise KeyError(f"Project {project.id} not found")
            conn.commit()
        return project
    def list_summaries(
        self,
        *,
        owner_id: str | None = None,
        org_id: str | None = None,
    ) -> list[ProjectSummary]:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            clauses: list[str] = []
            params: list[object] = []
            if "deleted_at" in cols:
                clauses.append("deleted_at IS NULL")
            if org_id is not None and "org_id" in cols:
                clauses.append("org_id = ?")
                params.append(org_id)
            elif owner_id is not None and "owner_id" in cols:
                clauses.append("owner_id = ?")
                params.append(owner_id)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT data FROM projects {where} ORDER BY updated_at DESC",
                tuple(params),
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

    def delete(
        self,
        project_id: str,
        *,
        org_id: str | None = None,
        soft: bool = True,
    ) -> bool:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            clauses = ["id = ?"]
            params: list[object] = [project_id]
            if org_id is not None and "org_id" in cols:
                clauses.append("org_id = ?")
                params.append(org_id)
            where = " AND ".join(clauses)
            if soft and "deleted_at" in cols:
                from datetime import datetime, timezone

                cur = conn.execute(
                    f"UPDATE projects SET deleted_at = ? WHERE {where} AND deleted_at IS NULL",
                    (datetime.now(timezone.utc).isoformat(), *params),
                )
            else:
                cur = conn.execute(f"DELETE FROM projects WHERE {where}", tuple(params))
            conn.commit()
            return cur.rowcount > 0

    def get_owner(self, project_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "owner_id" not in cols:
                return None
            clauses = ["id = ?"]
            if "deleted_at" in cols:
                clauses.append("deleted_at IS NULL")
            row = conn.execute(
                f"SELECT owner_id FROM projects WHERE {' AND '.join(clauses)}",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        return row["owner_id"]

    def get_org_id(self, project_id: str) -> str | None:
        with self._lock, self._connect() as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(projects)").fetchall()}
            if "org_id" not in cols:
                return None
            clauses = ["id = ?"]
            if "deleted_at" in cols:
                clauses.append("deleted_at IS NULL")
            row = conn.execute(
                f"SELECT org_id FROM projects WHERE {' AND '.join(clauses)}",
                (project_id,),
            ).fetchone()
        if not row:
            return None
        return row["org_id"]


def dump_project_snapshot(project: ProjectState) -> dict:
    """Compact snapshot for prompts — never includes secrets."""
    return json.loads(
        project.model_dump_json(
            exclude={"messages": {"__all__": {"metadata"}}},
        )
    )
