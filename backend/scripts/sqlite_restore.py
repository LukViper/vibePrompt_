#!/usr/bin/env python3
"""
Restore a VibePrompt SQLite backup into place.

Stops writers first (stop the API container). Verifies backup integrity before
replacing the live database.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def restore_database(
    *,
    backup: Path,
    database: Path,
    keep_previous: bool = True,
) -> Path:
    if not backup.exists():
        raise FileNotFoundError(f"Backup not found: {backup}")

    # Verify backup before touching live DB
    conn = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"Backup failed integrity_check: {row}")
        # Touch a cheap query to ensure readable schema
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        if not tables:
            raise RuntimeError("Backup contains no tables")
    finally:
        conn.close()

    database.parent.mkdir(parents=True, exist_ok=True)
    previous: Path | None = None
    if database.exists() and keep_previous:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        previous = database.with_name(f"{database.name}.pre-restore-{stamp}")
        shutil.copy2(database, previous)
        # Also move WAL/SHM aside if present
        for suffix in ("-wal", "-shm"):
            side = Path(str(database) + suffix)
            if side.exists():
                shutil.copy2(side, Path(str(previous) + suffix))

    # Atomic-ish replace: copy to temp then replace
    tmp = database.with_suffix(database.suffix + ".restoring")
    shutil.copy2(backup, tmp)
    tmp.replace(database)
    # Remove stale WAL/SHM so SQLite opens the restored main file cleanly
    for suffix in ("-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)

    # Post-restore integrity
    live = sqlite3.connect(database)
    try:
        row = live.execute("PRAGMA integrity_check").fetchone()
        if not row or row[0] != "ok":
            raise RuntimeError(f"Restored DB integrity_check failed: {row}")
    finally:
        live.close()

    print(f"RESTORE_OK: {database}")
    if previous:
        print(f"PREVIOUS_SAVED: {previous}")
    return database


def main() -> int:
    parser = argparse.ArgumentParser(description="Restore VibePrompt SQLite backup")
    parser.add_argument("--backup", required=True, help="Path to .db backup file")
    parser.add_argument(
        "--database",
        default="/data/vibeprompt.db",
        help="Live database path to replace",
    )
    parser.add_argument(
        "--no-keep-previous",
        action="store_true",
        help="Do not retain a copy of the previous live database",
    )
    args = parser.parse_args()
    try:
        restore_database(
            backup=Path(args.backup),
            database=Path(args.database),
            keep_previous=not args.no_keep_previous,
        )
    except Exception as exc:
        print(f"RESTORE_FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
