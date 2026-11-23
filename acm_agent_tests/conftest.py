import pytest

from acm_agent.memory.session import SessionStore


@pytest.fixture(autouse=True)
def isolated_sessions(tmp_path, monkeypatch):
    """API tests never write to a developer's real conversation database."""
    monkeypatch.setattr("acm_agent.api.app.store", SessionStore(tmp_path / "sessions.db"))
    # Never charge a developer's configured provider while running the offline test suite.
    monkeypatch.setenv("ACM_MODEL_PROVIDER", "openai")
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL", "DEEPSEEK_API_KEY"):
        monkeypatch.setenv(name, "")
