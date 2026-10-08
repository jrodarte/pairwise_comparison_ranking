import pytest

from pairwise_prioritizer.comparison_engine import create_project
from pairwise_prioritizer.models import Item


@pytest.fixture
def project():
    return create_project("Test", [Item(name=name) for name in "ABCD"], seed=17)


class MemoryKeyring:
    def __init__(self):
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.secrets.get((service, user))

    def set_password(self, service, user, secret):
        self.secrets[(service, user)] = secret

    def delete_password(self, service, user):
        self.secrets.pop((service, user), None)


@pytest.fixture(autouse=True)
def isolated_ai(monkeypatch):
    """Tests never touch the real OS keyring, provider env vars or any live AI endpoint."""
    from thinktui import ai, credentials

    keyring = MemoryKeyring()
    monkeypatch.setattr(credentials, "_backend", lambda: keyring)
    monkeypatch.setattr(credentials, "_session_keys", {})
    for preset in ai.PRESETS.values():
        if preset.key_env:
            monkeypatch.delenv(preset.key_env, raising=False)

    def offline(*_args, **_kwargs):
        raise RuntimeError("Could not reach AI provider (network disabled in tests)")

    monkeypatch.setattr(ai, "_request", offline)
    monkeypatch.setattr(ai, "_lines", offline)
    return keyring
