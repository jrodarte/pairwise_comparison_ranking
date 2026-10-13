"""A failed OS-keyring replacement cannot silently revive an obsolete credential."""

import pytest

from thinktui import credentials


def test_failed_write_removes_stale_key_before_session_fallback(isolated_ai, monkeypatch):
    ring = isolated_ai
    ring.secrets[(credentials.SERVICE, "openai")] = "old-key"

    def refuse_write(*args):
        raise RuntimeError("secret should not be echoed")

    monkeypatch.setattr(ring, "set_password", refuse_write)
    assert credentials.set_key("openai", "new-key") == "session"
    assert credentials.get_key("openai") == ("new-key", "session")
    credentials._session_keys.clear()  # simulate relaunch after the failed write
    assert credentials.get_key("openai") == (None, "none")
    assert (credentials.SERVICE, "openai") not in ring.secrets


def test_failed_write_and_delete_warn_instead_of_claiming_persistence(isolated_ai, monkeypatch):
    ring = isolated_ai
    ring.secrets[(credentials.SERVICE, "openai")] = "old-key"

    def fail(*args):
        raise RuntimeError("secret should not be echoed")

    monkeypatch.setattr(ring, "set_password", fail)
    monkeypatch.setattr(ring, "delete_password", fail)
    with pytest.raises(RuntimeError, match="before restarting") as error:
        credentials.set_key("openai", "new-key")
    assert "old-key" not in str(error.value) and "new-key" not in str(error.value)
    assert credentials.get_key("openai") == ("new-key", "session")
    assert ring.secrets[(credentials.SERVICE, "openai")] == "old-key"  # explicit warning required
    with pytest.raises(RuntimeError, match="credential manager"):
        credentials.forget_key("openai")
