from __future__ import annotations

import logging
from pathlib import Path

from acm_agent.agents.coach import Coach, ModelUnavailable
from acm_agent.memory.session import SessionStore

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError:  # allows importing the package before `uv sync`
    FastAPI = None

logger = logging.getLogger(__name__)

coach = Coach()
store = SessionStore()

if FastAPI:
    app = FastAPI(title="ACM Agent", version="0.1.0")
    web_directory = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web_directory), name="static")

    class ChatRequest(BaseModel):
        message: str = Field(min_length=1, max_length=100_000)
        session_id: str | None = None

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_directory / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str) -> dict:
        if not store.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"session_id": session_id, "messages": store.history(session_id)}

    @app.post("/chat")
    async def chat(request: ChatRequest) -> dict:
        session_id = store.ensure_session(request.session_id)
        history = store.history(session_id)
        store.add_message(session_id, "user", request.message)
        try:
            answer, tool_result = await coach.chat_async(request.message, history)
        except ModelUnavailable as exc:
            # The model is unreachable, but a local tool may still have produced verified
            # facts. Prefer those over an empty error: never lose real execution evidence.
            logger.warning("model unavailable: %s", exc.reason)
            if not exc.tool_result:
                raise HTTPException(
                    status_code=502,
                    detail=f"模型服务不可用：{exc.reason}",
                ) from exc
            answer = exc.local_answer
            tool_result = exc.tool_result
            store.add_message(session_id, "assistant", answer)
            return {
                "answer": answer,
                "session_id": session_id,
                "tool_result": tool_result,
                "degraded": True,
                "model_error": exc.reason,
            }
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("chat failed")
            raise HTTPException(status_code=500, detail=f"内部错误：{exc}") from exc
        store.add_message(session_id, "assistant", answer)
        return {"answer": answer, "session_id": session_id, "tool_result": tool_result}
else:
    app = None
