"""SQLite helpers: settings storage and a write-back audit log."""

import sqlite3
from contextlib import contextmanager

import config


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables and seed default settings if they are missing."""
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS writeback_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ts              TEXT    NOT NULL,
                event_id        TEXT,
                endpoint        TEXT,
                request_json    TEXT,
                response_status INTEGER,
                response_body   TEXT,
                ok              INTEGER
            )
            """
        )
        existing = {row["key"] for row in conn.execute("SELECT key FROM settings")}
        for key, value in config.DEFAULT_SETTINGS.items():
            if key not in existing:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)", (key, value)
                )


def get_settings():
    """Return all settings as a dict, backfilling any missing defaults."""
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    settings = dict(config.DEFAULT_SETTINGS)
    settings.update({row["key"]: row["value"] for row in rows})
    return settings


def get_setting(key, default=None):
    return get_settings().get(key, default)


def update_settings(values: dict):
    with get_conn() as conn:
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


def log_writeback(ts, event_id, endpoint, request_json, response_status, response_body, ok):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO writeback_log
                (ts, event_id, endpoint, request_json, response_status, response_body, ok)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, event_id, endpoint, request_json, response_status, response_body, int(bool(ok))),
        )


def get_writeback_logs(limit=50):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM writeback_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
