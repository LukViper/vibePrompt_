"""Validate that download/acquisition sources are legitimate."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

# Explicit denylist — never fetch from these.
BLOCKED_HOST_FRAGMENTS = (
    "thepiratebay",
    "1337x",
    "libgen",
    "librarygenesis",
    "z-library",
    "zlib",
    "sci-hub",
    "annas-archive",
    "torrent",
    "rutracker",
    "kickasstorrents",
)

# Hosts allowed for metadata and (when explicitly authorized) downloads.
ALLOWED_HOST_SUFFIXES = (
    "oreilly.com",
    "penguinrandomhouse.com",
    "abookapart.com",
    "momtestbook.com",
    "producttalk.org",
    "huyenchip.com",
    "archive.org",
    "openlibrary.org",
    "gutenberg.org",
    "google.com",
    "books.google.com",
    "worldcat.org",
    "amazon.com",
    "barnesandnoble.com",
    "bookshop.org",
)


@dataclass
class SourceValidationResult:
    ok: bool
    reason: str
    host: str | None = None


def _host(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.scheme not in {"http", "https"}:
        return None
    return (parsed.hostname or "").lower()


def is_blocked_url(url: str) -> bool:
    host = _host(url) or ""
    hay = f"{host} {url}".lower()
    return any(frag in hay for frag in BLOCKED_HOST_FRAGMENTS)


def is_allowed_host(url: str) -> bool:
    host = _host(url)
    if not host:
        return False
    return any(host == suf or host.endswith("." + suf) for suf in ALLOWED_HOST_SUFFIXES)


def validate_source_url(url: str, *, for_download: bool = False) -> SourceValidationResult:
    if not url or not url.strip():
        return SourceValidationResult(ok=False, reason="Empty URL")
    host = _host(url)
    if host is None:
        return SourceValidationResult(ok=False, reason="Invalid URL scheme or host")
    if is_blocked_url(url):
        return SourceValidationResult(
            ok=False,
            reason="Blocked: unauthorized or pirate source",
            host=host,
        )
    if for_download and not is_allowed_host(url):
        return SourceValidationResult(
            ok=False,
            reason="Download refused: host not on allowlist",
            host=host,
        )
    return SourceValidationResult(ok=True, reason="OK", host=host)
