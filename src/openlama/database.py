"""Database layer – schema, migrations, CRUD."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from openlama.config import DATA_DIR, DEFAULT_MODEL_PARAMS, DEFAULT_SYSTEM_PROMPT


# ── Paths ────────────────────────────────────────────────

DB_PATH = DATA_DIR / "openlama.db"


# ── Helpers ───────────────────────────────────────────────

def now_ts() -> int:
    return int(time.time())


def db_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ── Dataclasses ───────────────────────────────────────────

@dataclass
class UserState:
    telegram_id: int
    auth_until: int = 0
    state: str = ""
    selected_model: str = ""
    login_fail_count: int = 0
    login_lock_until: int = 0
    system_prompt: str = ""
    think_mode: int = 0


@dataclass
class ModelSettings:
    user_id: int
    model: str = ""
    temperature: float = DEFAULT_MODEL_PARAMS["temperature"]
    top_p: float = DEFAULT_MODEL_PARAMS["top_p"]
    top_k: int = DEFAULT_MODEL_PARAMS["top_k"]
    num_ctx: int = DEFAULT_MODEL_PARAMS["num_ctx"]
    num_predict: int = DEFAULT_MODEL_PARAMS["num_predict"]
    repeat_penalty: float = DEFAULT_MODEL_PARAMS["repeat_penalty"]
    seed: int = DEFAULT_MODEL_PARAMS["seed"]
    keep_alive: str = DEFAULT_MODEL_PARAMS["keep_alive"]


# ── Schema & Migration ────────────────────────────────────

def init_db():
    with db_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                auth_until INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT '',
                selected_model TEXT NOT NULL DEFAULT '',
                login_fail_count INTEGER NOT NULL DEFAULT 0,
                login_lock_until INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS contexts (
                user_id INTEGER PRIMARY KEY,
                items_json TEXT NOT NULL DEFAULT '[]',
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS allow_list (
                telegram_id INTEGER PRIMARY KEY,
                added_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
            )
        """)
        _migrate(conn)


def _migrate(conn: sqlite3.Connection):
    """Safely add columns / tables for upgrade – preserves existing data."""
    existing_user_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    migrations = {
        "system_prompt": "ALTER TABLE users ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''",
        "think_mode": "ALTER TABLE users ADD COLUMN think_mode INTEGER NOT NULL DEFAULT 0",
    }
    for col, ddl in migrations.items():
        if col not in existing_user_cols:
            conn.execute(ddl)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_model_settings (
            user_id INTEGER NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            temperature REAL,
            top_p REAL,
            top_k INTEGER,
            num_ctx INTEGER,
            num_predict INTEGER,
            repeat_penalty REAL,
            seed INTEGER,
            keep_alive TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s','now')),
            PRIMARY KEY (user_id, model)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            input_json TEXT,
            output_json TEXT,
            success INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cron_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cron_expr TEXT NOT NULL,
            task TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'telegram',
            chat_id INTEGER,
            enabled INTEGER NOT NULL DEFAULT 1,
            last_run INTEGER NOT NULL DEFAULT 0,
            next_run INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s','now'))
        )
    """)


# ── Settings (global key-value) ──────────────────────────

def get_setting(key: str) -> Optional[str]:
    with db_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO settings(key, value, updated_at)
               VALUES(?, ?, strftime('%s','now'))
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=strftime('%s','now')""",
            (key, value),
        )


def get_admin_password_hash() -> str:
    return get_setting("admin_password_hash") or ""


def set_admin_password_hash(new_hash: str):
    set_setting("admin_password_hash", new_hash)


# ── Users ─────────────────────────────────────────────────

def get_user(uid: int) -> UserState:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (uid,)).fetchone()
        if not row:
            conn.execute("INSERT INTO users(telegram_id) VALUES(?)", (uid,))
            row = conn.execute("SELECT * FROM users WHERE telegram_id=?", (uid,)).fetchone()
    keys = row.keys()
    return UserState(
        telegram_id=row["telegram_id"],
        auth_until=row["auth_until"],
        state=row["state"],
        selected_model=row["selected_model"],
        login_fail_count=row["login_fail_count"],
        login_lock_until=row["login_lock_until"],
        system_prompt=row["system_prompt"] if "system_prompt" in keys else "",
        think_mode=row["think_mode"] if "think_mode" in keys else 0,
    )


def update_user(uid: int, **kwargs):
    if not kwargs:
        return
    keys = list(kwargs.keys())
    vals = [kwargs[k] for k in keys]
    sets = ", ".join([f"{k}=?" for k in keys] + ["updated_at=strftime('%s','now')"])
    with db_conn() as conn:
        conn.execute(f"UPDATE users SET {sets} WHERE telegram_id=?", (*vals, uid))


def is_authed(user: UserState) -> bool:
    return user.auth_until > now_ts()


def is_login_locked(user: UserState) -> bool:
    return user.login_lock_until > now_ts()


# ── Context ───────────────────────────────────────────────

def clear_context(uid: int):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO contexts(user_id, items_json, updated_at)
               VALUES(?, '[]', strftime('%s','now'))
               ON CONFLICT(user_id) DO UPDATE SET items_json='[]', updated_at=strftime('%s','now')""",
            (uid,),
        )


def load_context(uid: int) -> list[dict]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT items_json FROM contexts WHERE user_id=?", (uid,)
        ).fetchone()
    if not row:
        return []
    try:
        items = json.loads(row["items_json"])
        if not isinstance(items, list):
            return []
        return items
    except Exception:
        return []


def save_context(uid: int, items: list[dict]):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO contexts(user_id, items_json, updated_at)
               VALUES(?, ?, strftime('%s','now'))
               ON CONFLICT(user_id) DO UPDATE SET items_json=excluded.items_json, updated_at=strftime('%s','now')""",
            (uid, json.dumps(items, ensure_ascii=False)),
        )


# ── User Model Settings ──────────────────────────────────

def get_model_settings(uid: int, model: str = "") -> ModelSettings:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_model_settings WHERE user_id=? AND model=?",
            (uid, model),
        ).fetchone()
    if not row:
        return ModelSettings(user_id=uid, model=model)
    return ModelSettings(
        user_id=row["user_id"],
        model=row["model"],
        temperature=row["temperature"] if row["temperature"] is not None else DEFAULT_MODEL_PARAMS["temperature"],
        top_p=row["top_p"] if row["top_p"] is not None else DEFAULT_MODEL_PARAMS["top_p"],
        top_k=row["top_k"] if row["top_k"] is not None else DEFAULT_MODEL_PARAMS["top_k"],
        num_ctx=row["num_ctx"] if row["num_ctx"] is not None else DEFAULT_MODEL_PARAMS["num_ctx"],
        num_predict=row["num_predict"] if row["num_predict"] is not None else DEFAULT_MODEL_PARAMS["num_predict"],
        repeat_penalty=row["repeat_penalty"] if row["repeat_penalty"] is not None else DEFAULT_MODEL_PARAMS["repeat_penalty"],
        seed=row["seed"] if row["seed"] is not None else DEFAULT_MODEL_PARAMS["seed"],
        keep_alive=row["keep_alive"] if row["keep_alive"] is not None else DEFAULT_MODEL_PARAMS["keep_alive"],
    )


def set_model_setting(uid: int, model: str, key: str, value: Any):
    with db_conn() as conn:
        conn.execute(
            f"""INSERT INTO user_model_settings(user_id, model, {key}, updated_at)
                VALUES(?, ?, ?, strftime('%s','now'))
                ON CONFLICT(user_id, model) DO UPDATE SET {key}=excluded.{key}, updated_at=strftime('%s','now')""",
            (uid, model, value),
        )


def reset_model_settings(uid: int, model: str = ""):
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM user_model_settings WHERE user_id=? AND model=?",
            (uid, model),
        )


# ── Tool call logging ────────────────────────────────────

def log_tool_call(uid: int, tool_name: str, input_data: Any, output_data: Any, success: bool = True):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO tool_calls(user_id, tool_name, input_json, output_json, success)
               VALUES(?, ?, ?, ?, ?)""",
            (
                uid,
                tool_name,
                json.dumps(input_data, ensure_ascii=False, default=str)[:5000],
                json.dumps(output_data, ensure_ascii=False, default=str)[:5000] if output_data else None,
                1 if success else 0,
            ),
        )


# ── Allow List ────────────────────────────────────────────

def get_allowed_ids() -> list[int]:
    with db_conn() as conn:
        rows = conn.execute("SELECT telegram_id FROM allow_list").fetchall()
    return [row["telegram_id"] for row in rows]


def add_allowed_id(tid: int):
    with db_conn() as conn:
        conn.execute(
            """INSERT INTO allow_list(telegram_id, added_at)
               VALUES(?, strftime('%s','now'))
               ON CONFLICT(telegram_id) DO NOTHING""",
            (tid,),
        )


def remove_allowed_id(tid: int):
    with db_conn() as conn:
        conn.execute("DELETE FROM allow_list WHERE telegram_id=?", (tid,))


def is_allowed(tid: int) -> bool:
    """Check if a telegram ID is in the allow list. Empty list = first login pending."""
    allowed = get_allowed_ids()
    if not allowed:
        return True  # empty list = first login pending
    return tid in allowed


# ── Cron Jobs ────────────────────────────────────────────

def create_cron_job(cron_expr: str, task: str, channel: str = "telegram",
                    chat_id: int = 0, created_by: int = 0, next_run: int = 0) -> int:
    with db_conn() as conn:
        cur = conn.execute(
            """INSERT INTO cron_jobs(cron_expr, task, channel, chat_id, enabled, next_run, created_by, created_at)
               VALUES(?, ?, ?, ?, 1, ?, ?, strftime('%s','now'))""",
            (cron_expr, task, channel, chat_id, next_run, created_by),
        )
        return cur.lastrowid


def list_cron_jobs(enabled_only: bool = False) -> list[dict]:
    with db_conn() as conn:
        if enabled_only:
            rows = conn.execute("SELECT * FROM cron_jobs WHERE enabled=1 ORDER BY id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM cron_jobs ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def get_cron_job(job_id: int) -> Optional[dict]:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM cron_jobs WHERE id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def delete_cron_job(job_id: int) -> bool:
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM cron_jobs WHERE id=?", (job_id,))
    return cur.rowcount > 0


def update_cron_job(job_id: int, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    with db_conn() as conn:
        conn.execute(f"UPDATE cron_jobs SET {sets} WHERE id=?", vals)


def get_due_cron_jobs(now_ts: int) -> list[dict]:
    """Get all enabled jobs where next_run <= now."""
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM cron_jobs WHERE enabled=1 AND next_run > 0 AND next_run <= ?",
            (now_ts,),
        ).fetchall()
    return [dict(row) for row in rows]
