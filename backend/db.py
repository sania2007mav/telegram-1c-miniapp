from __future__ import annotations

import sqlite3
from pathlib import Path

from config import settings


def connect() -> sqlite3.Connection:
    path = Path(settings.database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              telegram_id INTEGER NOT NULL UNIQUE,
              phone TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              owner_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              odata_url TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS odata_credentials (
              base_id INTEGER PRIMARY KEY REFERENCES bases(id) ON DELETE CASCADE,
              login TEXT NOT NULL,
              password_encrypted BLOB NOT NULL,
              updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS base_access (
              base_id INTEGER NOT NULL REFERENCES bases(id) ON DELETE CASCADE,
              phone TEXT NOT NULL,
              created_at TEXT NOT NULL DEFAULT (datetime('now')),
              PRIMARY KEY (base_id, phone)
            );

            CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone);
            CREATE INDEX IF NOT EXISTS idx_base_access_phone ON base_access(phone);
            """
        )


def upsert_user(telegram_id: int, phone: str) -> sqlite3.Row:
    phone = normalize_phone(phone)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, phone) VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET phone = excluded.phone
            """,
            (telegram_id, phone),
        )
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        assert row is not None
        return row


def get_user_by_telegram(telegram_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()


def list_bases_for_phone(phone: str) -> list[sqlite3.Row]:
    phone = normalize_phone(phone)
    with connect() as conn:
        return list(
            conn.execute(
                """
                SELECT b.*, u.phone AS owner_phone,
                       CASE WHEN u.phone = ? THEN 1 ELSE 0 END AS is_owner
                FROM bases b
                JOIN users u ON u.id = b.owner_user_id
                WHERE u.phone = ?
                   OR EXISTS (
                     SELECT 1 FROM base_access a
                     WHERE a.base_id = b.id AND a.phone = ?
                   )
                ORDER BY b.id DESC
                """,
                (phone, phone, phone),
            )
        )


def normalize_phone(phone: str) -> str:
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return digits
