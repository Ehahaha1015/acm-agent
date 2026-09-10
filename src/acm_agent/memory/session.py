from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from acm_agent.textutil import sanitize_text


class SessionStore:
    def __init__(self, path: str | Path = "workspace/acm_agent.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
            db.execute("CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        with self._connect() as db:
            db.execute("INSERT INTO sessions(id) VALUES (?)", (session_id,))
        return session_id

    def ensure_session(self, session_id: str | None) -> str:
        if session_id and self.session_exists(session_id):
            return session_id
        return self.create_session()

    def session_exists(self, session_id: str) -> bool:
        with self._connect() as db:
            return db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone() is not None

    def add_message(self, session_id: str, role: str, content: str) -> None:
        # SQLite encodes to UTF-8 on insert, so a lone surrogate would raise here.
        safe = sanitize_text(content)
        with self._connect() as db:
            db.execute("INSERT INTO messages(session_id, role, content) VALUES (?, ?, ?)", (session_id, role, safe))

    def history(self, session_id: str) -> list[dict[str, str]]:
        with self._connect() as db:
            rows = db.execute("SELECT role, content FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        return [{"role": role, "content": content} for role, content in rows]
