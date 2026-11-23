from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from acm_agent import __version__
from acm_agent.agents.coach import Coach, ModelUnavailable
from acm_agent.config import get_settings
from acm_agent.diagnostics import runtime_status
from acm_agent.execution.backend import reset_backend
from acm_agent.execution.languages import Language
from acm_agent.memory.session import SessionStore
from acm_agent.tools import check_code, compare_code, run_code, stress_code

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field, field_validator, model_validator
except ImportError:  # allows importing the package before `uv sync`
    FastAPI = None

logger = logging.getLogger(__name__)

coach = Coach()
store = SessionStore(get_settings().database)
execution_slots = threading.BoundedSemaphore(2)

if FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        yield
        reset_backend()

    app = FastAPI(title="ACM Agent", version=__version__, lifespan=lifespan)
    web_directory = Path(__file__).with_name("web")
    app.mount("/static", StaticFiles(directory=web_directory), name="static")

    class ChatRequest(BaseModel):
        message: str = Field(min_length=1, max_length=100_000)
        session_id: str | None = None

        @field_validator("message")
        @classmethod
        def nonempty(cls, value: str) -> str:
            if not value.strip():
                raise ValueError("消息不能为空")
            return value

    class ExecuteRequest(BaseModel):
        mode: Literal["compile", "run", "compare", "stress"] = "run"
        language: Language = "cpp"
        reference_language: Language | None = None
        generator_language: Language | None = None
        code: str = Field(min_length=1, max_length=100_000)
        input_data: str = Field(default="", max_length=100_000)
        reference_code: str = Field(default="", max_length=100_000)
        generator_code: str = Field(default="", max_length=100_000)
        test_cases: list[str] = Field(default_factory=list, max_length=100)
        iterations: int = Field(default=100, ge=1, le=1000)
        start_seed: int = Field(default=1, ge=0, le=2**63 - 1001)
        timeout: float = Field(default=2.0, ge=0.05, le=10.0)

        @model_validator(mode="after")
        def validate_sources(self):
            if not self.code.strip():
                raise ValueError("请提供源代码")
            if self.mode in {"compare", "stress"} and not self.reference_code.strip():
                raise ValueError("差分与对拍需要参考程序")
            if self.mode == "stress" and not self.generator_code.strip():
                raise ValueError("随机对拍需要生成器")
            if sum(map(len, self.test_cases)) > 100_000:
                raise ValueError("测试数据总长度不能超过 100000")
            return self

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(web_directory / "index.html")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/status")
    def status() -> dict:
        return runtime_status()

    @app.get("/sessions")
    def sessions() -> dict:
        return {"sessions": store.list_sessions()}

    @app.delete("/sessions/{session_id}")
    def delete_session(session_id: str) -> dict:
        if not store.delete_session(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"deleted": True}

    @app.post("/execute")
    def execute(request: ExecuteRequest) -> dict:
        if not execution_slots.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="执行任务已满，请稍后重试")
        started = time.monotonic()
        trace = []
        try:
            if request.mode == "compile":
                result = check_code(request.code, language=request.language)
            elif request.mode == "run":
                result = run_code(
                    request.code, request.input_data, timeout=request.timeout, progress=trace.append,
                    language=request.language,
                )
            elif request.mode == "compare":
                result = compare_code(
                    request.code, request.reference_code,
                    request.test_cases or [request.input_data],
                    timeout=request.timeout, progress=trace.append,
                    budget_seconds=30.0,
                    language=request.language, reference_language=request.reference_language,
                )
            else:
                result = stress_code(
                    request.code, request.reference_code, request.generator_code,
                    iterations=request.iterations, start_seed=request.start_seed,
                    timeout=request.timeout, progress=trace.append, budget_seconds=30.0,
                    language=request.language, reference_language=request.reference_language,
                    generator_language=request.generator_language,
                )
            return {
                "result": result, "trace": trace,
                "languages": {
                    "candidate": request.language,
                    "reference": request.reference_language or request.language,
                    "generator": request.generator_language or request.language,
                },
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        finally:
            execution_slots.release()

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str) -> dict:
        if not store.session_exists(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return {"session_id": session_id, "messages": store.history(session_id)}

    @app.post("/chat")
    async def chat(request: ChatRequest) -> dict:
        if request.session_id and not store.session_exists(request.session_id):
            raise HTTPException(status_code=404, detail="Session not found")
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
            store.add_message(session_id, "assistant", answer, tool_result)
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
            raise HTTPException(status_code=500, detail="内部错误，请查看服务日志") from exc
        store.add_message(session_id, "assistant", answer, tool_result)
        return {"answer": answer, "session_id": session_id, "tool_result": tool_result}
else:
    app = None
