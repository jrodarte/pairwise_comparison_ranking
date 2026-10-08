"""API-key lookup and storage. Keys live in the OS keyring or process memory only, never SQLite/exports/logs."""

from __future__ import annotations

import os

SERVICE = "thinktui"
_session_keys: dict[str, str] = {}


def _backend():
    """Return the OS keyring module, or None when no usable keyring is installed/configured."""
    try:
        import keyring
        from keyring.backends.fail import Keyring as FailKeyring

        if isinstance(keyring.get_keyring(), FailKeyring):
            return None
        return keyring
    except Exception:
        return None


def keyring_available() -> bool:
    return _backend() is not None


def get_key(provider_id: str, env_var: str = "") -> tuple[str | None, str]:
    """Return (key, source) with precedence: session entry, OS keyring, environment variable."""
    if provider_id in _session_keys:
        return _session_keys[provider_id], "session"
    backend = _backend()
    if backend is not None:
        try:
            key = backend.get_password(SERVICE, provider_id)
        except Exception:
            key = None
        if key:
            return key, "keyring"
    if env_var and os.environ.get(env_var):
        return os.environ[env_var], f"${env_var}"
    return None, "none"


def set_key(provider_id: str, key: str, remember: bool = True) -> str:
    """Store a key; returns where it went ("keyring" or "session")."""
    key = key.strip()
    if not key:
        raise ValueError("API key is empty")
    backend = _backend() if remember else None
    if backend is not None:
        try:
            backend.set_password(SERVICE, provider_id, key)
            _session_keys.pop(provider_id, None)
            return "keyring"
        except Exception:
            pass
    _session_keys[provider_id] = key
    return "session"


def forget_key(provider_id: str) -> None:
    _session_keys.pop(provider_id, None)
    backend = _backend()
    if backend is not None:
        try:
            backend.delete_password(SERVICE, provider_id)
        except Exception:
            pass
