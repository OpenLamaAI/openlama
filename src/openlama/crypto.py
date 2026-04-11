"""Symmetric encryption for storing secrets (OAuth tokens, API keys) in the DB."""

import os
from pathlib import Path

from cryptography.fernet import Fernet

from openlama.config import DATA_DIR

_KEY_PATH = DATA_DIR / "secret.key"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Return a cached Fernet instance, generating the key file if needed."""
    global _fernet
    if _fernet is not None:
        return _fernet

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if _KEY_PATH.exists():
        key = _KEY_PATH.read_bytes().rstrip(b"\n\r")
    else:
        key = Fernet.generate_key()
        _KEY_PATH.write_bytes(key)

    # Always ensure restrictive permissions
    try:
        os.chmod(_KEY_PATH, 0o600)
    except OSError:
        pass

    _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string and return base64-encoded ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt base64-encoded ciphertext back to a string."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
