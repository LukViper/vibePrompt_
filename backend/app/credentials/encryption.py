"""Fernet encryption for BYOK API keys. Platform keys stay in env only."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _derive_fernet_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class CredentialCipher:
    def __init__(self, secret: str) -> None:
        if not secret or not secret.strip():
            raise ValueError("CREDENTIALS_ENCRYPTION_KEY is required when BYOK is used")
        self._fernet = Fernet(_derive_fernet_key(secret.strip()))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Unable to decrypt stored credential") from exc
