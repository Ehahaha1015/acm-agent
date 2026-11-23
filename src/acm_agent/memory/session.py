from __future__ import annotations

import json
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
            columns = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
            if "tool_result" not in columns:
                db.execute("ALTER TABLE messages ADD COLUMN tool_result TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id, id)")

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

    def add_message(
        self, session_id: str, role: str, content: str, tool_result: dict | None = None
    ) -> None:
        # SQLite encodes to UTF-8 on insert, so a lone surrogate would raise here.
        safe = sanitize_text(content)
        with self._connect() as db:
            db.execute(
                "INSERT INTO messages(session_id, role, content, tool_result) VALUES (?, ?, ?, ?)",
                (session_id, role, safe, json.dumps(tool_result) if tool_result else None),
            )

    def history(self, session_id: str) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT role, content, tool_result FROM messages WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [
            {"role": role, "content": content, **({"tool_result": json.loads(result)} if result else {})}
            for role, content, result in rows
        ]

    def list_sessions(self, limit: int = 100) -> list[dict]:
        with self._connect() as db:
            rows = db.execute(
                """SELECT s.id, s.created_at,
                (SELECT substr(content, 1, 70) FROM messages WHERE session_id=s.id
                 AND role='user' ORDER BY id LIMIT 1),
                (SELECT count(*) FROM messages WHERE session_id=s.id)
                FROM sessions s ORDER BY
                coalesce((SELECT max(id) FROM messages WHERE session_id=s.id), 0) DESC,
                s.created_at DESC LIMIT ?""", (limit,),
            ).fetchall()
        return [
            {"id": sid, "created_at": created, "title": title or "新对话", "message_count": count}
            for sid, created, title, count in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        with self._connect() as db:
            db.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
            return db.execute("DELETE FROM sessions WHERE id=?", (session_id,)).rowcount > 0
