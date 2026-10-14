from __future__ import annotations

from cryptography.fernet import Fernet

from config import settings


def _fernet() -> Fernet:
    key = settings.credentials_encryption_key.strip()
    if not key:
        raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY is not set")
    return Fernet(key.encode("ascii"))


def encrypt_password(password: str) -> bytes:
    return _fernet().encrypt(password.encode("utf-8"))


def decrypt_password(blob: bytes) -> str:
    return _fernet().decrypt(blob).decode("utf-8")
