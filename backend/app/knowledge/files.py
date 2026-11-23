"""Secure on-disk storage for uploaded knowledge files."""

from __future__ import annotations

import re
from pathlib import Path

from app.knowledge.acquisition.downloader import sha256_bytes

ALLOWED_EXTENSIONS = {".pdf", ".epub", ".txt", ".docx"}
MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".epub": "application/epub+zip",
    ".txt": "text/plain",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class FileValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\-]+", "_", base)
    return base[:180] or "upload.bin"


def ensure_under_root(path: Path | str, root: Path | str) -> Path:
    """
    Resolve `path` and require it to stay inside `root`.
    Rejects `../` traversal and absolute paths outside the upload tree.
    """
    root_resolved = Path(root).resolve()
    candidate = Path(path)
    # Disallow absolute escapes before resolve joins oddly on some platforms
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise FileValidationError("Path escapes knowledge upload root") from exc
    return resolved


def validate_extension(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    return ext


def store_upload(
    *,
    upload_root: Path,
    book_id: str,
    filename: str,
    data: bytes,
    max_bytes: int,
) -> dict[str, str | int]:
    if len(data) == 0:
        raise FileValidationError("Empty file")
    if len(data) > max_bytes:
        raise FileValidationError(f"File exceeds max size ({max_bytes} bytes)")
    ext = validate_extension(filename)
    dest_dir = upload_root / book_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe = safe_filename(filename)
    if not safe.lower().endswith(ext):
        safe = f"{safe}{ext}"
    path = ensure_under_root(dest_dir / safe, upload_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "path": str(path),
        "filename": safe,
        "mime_type": MIME_BY_EXT[ext],
        "size_bytes": len(data),
        "sha256": sha256_bytes(data),
        "ext": ext,
    }
