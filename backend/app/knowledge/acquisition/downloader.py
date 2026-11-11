"""Download manager — only authorized open/public-domain URLs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx

from app.knowledge.acquisition.licensing import evaluate_rights
from app.knowledge.acquisition.source_validator import validate_source_url
from app.knowledge.catalog import get_catalog_entry

ALLOWED_EXTENSIONS = {".pdf", ".epub", ".txt", ".docx"}
MAX_DOWNLOAD_BYTES = 40 * 1024 * 1024


class DownloadError(Exception):
    def __init__(self, message: str, code: str = "download_refused") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def attempt_authorized_download(
    slug: str,
    dest_dir: Path,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Download only if catalog marks full_text_authorized with a URL."""
    entry = get_catalog_entry(slug)
    if entry is None:
        raise DownloadError(f"Unknown catalog slug: {slug}", "unknown_slug")

    url = entry.get("authorized_download_url")
    if not entry.get("full_text_authorized") or not url:
        raise DownloadError(
            "No authorized full-text download for this title. "
            "Purchase, borrow via library, or upload a rights-confirmed copy.",
            "not_authorized",
        )

    decision = evaluate_rights(
        usage_permission="open_access" if entry.get("full_text_authorized") else "unknown",
        rights_confirmed=True,
        full_text_authorized=True,
        has_authorized_url=True,
    )
    if not decision.may_auto_download:
        raise DownloadError(decision.reason, "licensing_blocked")

    validation = validate_source_url(url, for_download=True)
    if not validation.ok:
        raise DownloadError(validation.reason, "source_blocked")

    dest_dir.mkdir(parents=True, exist_ok=True)
    own_client = client is None
    client = client or httpx.Client(timeout=60.0, follow_redirects=True)
    try:
        with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise DownloadError(
                    f"Download failed HTTP {resp.status_code}",
                    "http_error",
                )
            content_type = (resp.headers.get("content-type") or "").split(";")[0].strip()
            ext = _guess_ext(url, content_type)
            if ext not in ALLOWED_EXTENSIONS:
                raise DownloadError(f"Unsupported format: {ext}", "bad_format")

            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise DownloadError("File exceeds size limit", "too_large")
                chunks.append(chunk)
            data = b"".join(chunks)
    finally:
        if own_client:
            client.close()

    checksum = sha256_bytes(data)
    filename = f"{slug}{ext}"
    path = dest_dir / filename
    path.write_bytes(data)
    return {
        "slug": slug,
        "path": str(path),
        "filename": filename,
        "size_bytes": len(data),
        "sha256": checksum,
        "source_url": url,
        "downloaded": True,
        "content_type": content_type,
    }


def _guess_ext(url: str, content_type: str) -> str:
    lower = url.lower().split("?")[0]
    for ext in ALLOWED_EXTENSIONS:
        if lower.endswith(ext):
            return ext
    mapping = {
        "application/pdf": ".pdf",
        "application/epub+zip": ".epub",
        "text/plain": ".txt",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    }
    return mapping.get(content_type, ".bin")
