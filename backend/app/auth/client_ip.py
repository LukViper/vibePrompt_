"""Trusted client IP extraction — ignore spoofable forwarded headers by default."""

from __future__ import annotations

import hashlib
import ipaddress
from typing import Iterable

from fastapi import Request

from app.config import Settings


def _parse_cidrs(raw: str) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    nets: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for part in (raw or "").split(","):
        text = part.strip()
        if not text:
            continue
        try:
            nets.append(ipaddress.ip_network(text, strict=False))
        except ValueError:
            continue
    return nets


def _peer_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host.strip()
    return "unknown"


def _ip_in_trusted(peer: str, trusted: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network]) -> bool:
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in trusted)


def _first_forwarded(value: str | None) -> str | None:
    if not value:
        return None
    # X-Forwarded-For: client, proxy1, proxy2 — leftmost is original client when trusted
    first = value.split(",")[0].strip()
    if not first:
        return None
    try:
        ipaddress.ip_address(first)
    except ValueError:
        return None
    return first


def resolve_client_ip(request: Request, settings: Settings) -> str:
    """
    Return the client IP for rate limiting.

    Default: `request.client.host` only.
    When TRUSTED_PROXY_CIDRS is set and the peer is in that set, honor
    CF-Connecting-IP then the leftmost X-Forwarded-For hop.
    """
    peer = _peer_ip(request)
    trusted = _parse_cidrs(getattr(settings, "trusted_proxy_cidrs", "") or "")
    if not trusted or not _ip_in_trusted(peer, trusted):
        return peer or "unknown"

    cf = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf:
        try:
            ipaddress.ip_address(cf)
            return cf
        except ValueError:
            pass

    forwarded = _first_forwarded(request.headers.get("x-forwarded-for"))
    if forwarded:
        return forwarded
    return peer or "unknown"


def hash_client_ip(ip: str) -> str:
    return hashlib.sha256((ip or "unknown").encode("utf-8")).hexdigest()[:32]
