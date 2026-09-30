from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from profile_store import default_database_path

API_KEY_SETTING = "anthropic_api_key"
GEMINI_API_KEY_SETTING = "gemini_api_key"
PROVIDER_SETTING = "ai_provider"

DEFAULT_PROVIDER = "anthropic"
VALID_PROVIDERS = ("anthropic", "gemini")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mask(key: str | None) -> str | None:
    if not key:
        return None
    return f"…{key[-4:]}" if len(key) > 4 else "…" + key


class AiSettingsStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _get_setting(self, key: str) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def _set_setting(self, key: str, value: Any) -> None:
        cleaned = str(value or "").strip()
        with closing(self._connect()) as connection, connection:
            if not cleaned:
                connection.execute("DELETE FROM settings WHERE key = ?", (key,))
                return
            connection.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, cleaned, _utc_now()),
            )

    # Anthropic
    def get_api_key(self) -> str | None:
        return self._get_setting(API_KEY_SETTING)

    def get_api_key_masked(self) -> str | None:
        return _mask(self.get_api_key())

    def has_api_key(self) -> bool:
        return bool(self.get_api_key())

    def set_api_key(self, value: Any) -> None:
        self._set_setting(API_KEY_SETTING, value)

    # Google Gemini
    def get_gemini_api_key(self) -> str | None:
        return self._get_setting(GEMINI_API_KEY_SETTING)

    def get_gemini_api_key_masked(self) -> str | None:
        return _mask(self.get_gemini_api_key())

    def has_gemini_api_key(self) -> bool:
        return bool(self.get_gemini_api_key())

    def set_gemini_api_key(self, value: Any) -> None:
        self._set_setting(GEMINI_API_KEY_SETTING, value)

    # Active provider
    def get_provider(self) -> str:
        value = self._get_setting(PROVIDER_SETTING)
        return value if value in VALID_PROVIDERS else DEFAULT_PROVIDER

    def set_provider(self, value: Any) -> None:
        cleaned = str(value or "").strip()
        if cleaned not in VALID_PROVIDERS:
            raise ValueError(f"Ungültiger KI-Anbieter: {value!r}")
        self._set_setting(PROVIDER_SETTING, cleaned)
