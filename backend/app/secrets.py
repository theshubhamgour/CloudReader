"""API key storage: environment / .env first, then the OS keychain (via `keyring`).

If no keychain is available (e.g. a Linux machine without a keyring service), the key is
saved to a private file in the data folder (`data/.secrets/`, readable only by you).
Keys are never written to the database or logs.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)
SERVICE = "CloudReader"
GEMINI = "gemini-api-key"


def _keyring():
    try:
        import keyring

        return keyring
    except Exception:
        return None


def _file(name: str) -> Path:
    from .config import get_settings

    return get_settings().data_dir / ".secrets" / name


def get_secret(name: str) -> str | None:
    kr = _keyring()
    if kr is not None:
        try:
            if value := kr.get_password(SERVICE, name):
                return value
        except Exception as e:
            log.warning("Keychain read failed: %s", type(e).__name__)
    f = _file(name)
    if f.exists():
        return f.read_text(encoding="utf-8").strip() or None
    return None


def set_secret(name: str, value: str) -> str:
    """Store a secret. Returns where it went: 'keychain' or 'file'."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            return "keychain"
        except Exception as e:
            log.warning("Keychain write failed (%s); using the private key file instead.", type(e).__name__)
    f = _file(name)
    f.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(f.parent, 0o700)
    f.write_text(value, encoding="utf-8")
    os.chmod(f, 0o600)
    return "file"


def delete_secret(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    _file(name).unlink(missing_ok=True)


def mask(value: str | None) -> str | None:
    if not value:
        return None
    return value[:4] + "…" + value[-4:] if len(value) > 12 else "…"
