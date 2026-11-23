import pytest

from acm_agent.memory.session import SessionStore


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    """API tests never write to a developer's real conversation database."""
    monkeypatch.setattr("acm_agent.api.app.store", SessionStore(tmp_path / "sessions.db"))
