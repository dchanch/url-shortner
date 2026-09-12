import sqlite3

from app.config import DB_PATH


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_code TEXT UNIQUE NOT NULL,
                original_url TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'system',
                click_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_code TEXT NOT NULL,
                clicked_at TEXT NOT NULL,
                user_agent TEXT,
                referer TEXT,
                ip_address TEXT,
                FOREIGN KEY(short_code) REFERENCES links(short_code)
            )
            """
        )
        conn.commit()


def reset_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM clicks")
        conn.execute("DELETE FROM links")
        conn.commit()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
