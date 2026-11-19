"""TOTP MFA for paid accounts (stdlib + optional pyotp)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time


def generate_totp_secret() -> str:
    try:
        import pyotp

        return pyotp.random_base32()
    except ImportError:
        return base64.b32encode(os.urandom(20)).decode("ascii").rstrip("=")


def provisioning_uri(secret: str, email: str, issuer: str = "VibePrompt") -> str:
    try:
        import pyotp

        return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=issuer)
    except ImportError:
        return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}"


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret.upper() + "=" * ((8 - len(secret) % 8) % 8))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (
        (digest[offset] & 0x7F) << 24
        | (digest[offset + 1] & 0xFF) << 16
        | (digest[offset + 2] & 0xFF) << 8
        | (digest[offset + 3] & 0xFF)
    )
    return str(code % (10**digits)).zfill(digits)


def verify_totp(secret: str, code: str, *, window: int = 1) -> bool:
    code = (code or "").strip()
    if not code.isdigit():
        return False
    try:
        import pyotp

        return bool(pyotp.TOTP(secret).verify(code, valid_window=window))
    except ImportError:
        timestep = int(time.time() // 30)
        for drift in range(-window, window + 1):
            if hmac.compare_digest(_hotp(secret, timestep + drift), code):
                return True
        return False
