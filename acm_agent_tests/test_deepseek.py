import asyncio
import os
from types import SimpleNamespace

from fastapi.testclient import TestClient

from acm_agent.agents.coach import Coach
from acm_agent.api.app import app
from acm_agent.config import get_settings


def configure_deepseek(monkeypatch):
    monkeypatch.setenv("ACM_MODEL_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "local-test-secret-value")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-flash")


def test_deepseek_settings_use_official_endpoint(monkeypatch):
    configure_deepseek(monkeypatch)
    settings = get_settings()
    assert settings.llm_configured
    assert settings.is_deepseek
    assert settings.openai_base_url == "https://api.deepseek.com"
    assert settings.openai_model == "deepseek-flash"
    assert settings.openai_api_key not in repr(settings)


def test_dotenv_secret_does_not_enter_child_process_environment(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("ACM_MODEL_PROVIDER", "deepseek")
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=local-file-secret\n")
    assert get_settings().openai_api_key == "local-file-secret"
    assert "DEEPSEEK_API_KEY" not in os.environ


def test_deepseek_disables_thinking_and_beta_strict_schema(monkeypatch):
    configure_deepseek(monkeypatch)

    async def run(agent, prompt, **kwargs):
        assert agent.model_settings.extra_body == {"thinking": {"type": "disabled"}}
        assert agent.model_settings.max_tokens == 4096
        assert all(not tool.strict_json_schema for tool in agent.tools)
        return SimpleNamespace(final_output="connected", new_items=[])

    monkeypatch.setattr("agents.Runner.run", run)
    answer, _ = asyncio.run(Coach().chat_async("你好"))
    assert answer == "connected"


def test_provider_error_cannot_echo_key_into_response_or_logs(monkeypatch, caplog):
    configure_deepseek(monkeypatch)

    async def fail(*args, **kwargs):
        raise RuntimeError("Rejected Bearer local-test-secret-value")

    monkeypatch.setattr("agents.Runner.run", fail)
    with TestClient(app) as client:
        response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 502
    assert "local-test-secret-value" not in response.text
    assert "local-test-secret-value" not in caplog.text
    assert "[REDACTED]" in response.text


def test_status_exposes_model_name_without_credentials(monkeypatch):
    configure_deepseek(monkeypatch)
    with TestClient(app) as client:
        response = client.get("/status")
    assert response.json()["provider"] == "deepseek"
    assert response.json()["model_configured"]
    assert "local-test-secret-value" not in response.text
