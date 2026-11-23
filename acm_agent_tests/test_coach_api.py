from fastapi.testclient import TestClient

from acm_agent.agents.coach import Coach
from acm_agent.api.app import app

client = TestClient(app)


def test_web_chat_page_and_assets_are_served():
    response = client.get("/")
    assert response.status_code == 200
    assert "ACM Agent" in response.text
    assert 'id="chat-form"' in response.text
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_returns_session_and_answer(monkeypatch):
    async def fake_chat(message, history):
        return f"收到：{message}", None

    monkeypatch.setattr("acm_agent.api.app.coach.chat_async", fake_chat)
    response = client.post("/chat", json={"message": "请分析算法", "session_id": None})
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["answer"]
    assert "tool_result" in payload
    history = client.get(f"/sessions/{payload['session_id']}/messages")
    assert history.status_code == 200
    assert [item["role"] for item in history.json()["messages"][-2:]] == ["user", "assistant"]


def test_chat_rejects_empty_and_oversized_messages():
    assert client.post("/chat", json={"message": "", "session_id": None}).status_code == 422
    oversized = "x" * 100_001
    assert client.post("/chat", json={"message": oversized, "session_id": None}).status_code == 422


def test_unknown_session_history_returns_not_found():
    response = client.get("/sessions/not-a-real-session/messages")
    assert response.status_code == 404


def test_coach_does_not_treat_input_fence_as_reference():
    message = """```cpp
#include <iostream>
int main(){ int x; std::cin >> x; std::cout << x + 1; }
```
输入: ```
4
```
"""
    answer, result = Coach().chat(message)
    assert result is not None
    assert result["status"] == "OK"
    assert result["stdout"] == "5"
    assert "Tool result: OK" in answer
