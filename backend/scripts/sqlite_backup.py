#!/usr/bin/env python3
"""
Consistent SQLite backup using the SQLite Online Backup API (connection.backup).

Do NOT copy a live .db file with cp/rsync while writers are active.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path


def backup_database(
    *,
    database: Path,
    backup_dir: Path,
    retain: int = 14,
    label: str | None = None,
) -> Path:
    if not database.exists():
        raise FileNotFoundError(f"Database not found: {database}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{label}" if label else ""
    dest = backup_dir / f"vibeprompt-{stamp}{suffix}.db"

    src = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=60.0)
    try:
        # Brief checkpoint so WAL pages are included when applicable
        try:
            src.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass
        dst = sqlite3.connect(dest)
        try:
            with dst:
                src.backup(dst)
            # Integrity check on the backup itself
            row = dst.execute("PRAGMA integrity_check").fetchone()
            if not row or row[0] != "ok":
                raise RuntimeError(f"Backup integrity_check failed: {row}")
        finally:
            dst.close()
    finally:
        src.close()

    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(database),
        "backup": str(dest),
        "bytes": dest.stat().st_size,
        "integrity_check": "ok",
        "method": "sqlite3.Connection.backup",
    }
    meta_path = dest.with_suffix(".db.json")
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    _prune(backup_dir, retain=retain)
    return dest


def _prune(backup_dir: Path, *, retain: int) -> None:
    if retain <= 0:
        return
    backups = sorted(
        backup_dir.glob("vibeprompt-*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for stale in backups[retain:]:
        stale.unlink(missing_ok=True)
        stale.with_suffix(".db.json").unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite online backup for VibePrompt")
    parser.add_argument(
        "--database",
        default="/data/vibeprompt.db",
        help="Path to live SQLite database",
    )
    parser.add_argument(
        "--backup-dir",
        default="/data/backups",
        help="Directory for backup files",
    )
    parser.add_argument(
        "--retain",
        type=int,
        default=14,
        help="Number of newest backups to retain (0 = keep all)",
    )
    parser.add_argument("--label", default=None, help="Optional label suffix")
    args = parser.parse_args()

    try:
        dest = backup_database(
            database=Path(args.database),
            backup_dir=Path(args.backup_dir),
            retain=args.retain,
            label=args.label,
        )
    except Exception as exc:
        print(f"BACKUP_FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"BACKUP_OK: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
