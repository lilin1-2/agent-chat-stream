"""
会话存储引擎 —— SQLite 持久化 + Summary Memory

每个 Session 存一张表（或统一表），服务重启不丢。
对话过长时自动摘要压缩。
"""
import sqlite3
import json
import os

DB_PATH = "./chat_history.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summary (
            session_id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            up_to_msg_id INTEGER DEFAULT 0,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """)
    conn.commit()
    conn.close()


# ============================================================
# Session 操作
# ============================================================

def create_session(session_id: str, name: str = "") -> dict:
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO sessions (session_id, name) VALUES (?, ?)", (session_id, name))
    conn.commit()
    conn.close()
    return {"session_id": session_id, "name": name, "message_count": 0}


def get_all_sessions() -> list:
    conn = get_db()
    rows = conn.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_session(session_id: str):
    conn = get_db()
    conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM summary WHERE session_id = ?", (session_id,))
    conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()


# ============================================================
# 消息持久化
# ============================================================

def get_history(session_id: str) -> list:
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id ASC",
        (session_id,)
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def add_message(session_id: str, role: str, content: str):
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content)
    )
    conn.commit()
    conn.close()


def get_message_count(session_id: str) -> int:
    conn = get_db()
    count = conn.execute(
        "SELECT COUNT(*) as c FROM messages WHERE session_id = ?", (session_id,)
    ).fetchone()["c"]
    conn.close()
    return count


# ============================================================
# Summary Memory
# ============================================================

MAX_HISTORY_MESSAGES = 20  # 超过这个数触发摘要压缩


def get_summary(session_id: str) -> str:
    conn = get_db()
    row = conn.execute("SELECT content FROM summary WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row["content"] if row else ""


def save_summary(session_id: str, content: str, up_to_msg_id: int):
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO summary (session_id, content, up_to_msg_id) VALUES (?, ?, ?)",
        (session_id, content, up_to_msg_id)
    )
    conn.commit()
    conn.close()


# 初始化
os.makedirs(os.path.dirname(DB_PATH) if os.path.dirname(DB_PATH) else ".", exist_ok=True)
init_db()
