from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKUP_SCHEMA = "hbtec-modbus-profile-library"
BACKUP_VERSION = 1


def default_database_path() -> Path:
    override = os.getenv("HBMODBUS_DATA_DIR")
    if override:
        base = Path(override)
    elif os.name == "nt" and os.getenv("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "hbTec" / "ModbusInspector"
    else:
        xdg_data = os.getenv("XDG_DATA_HOME")
        base = Path(xdg_data) / "hbtec-modbus-inspector" if xdg_data else Path.home() / ".local" / "share" / "hbtec-modbus-inspector"
    return base / "profiles.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: Any, maximum: int = 500) -> str:
    return str(value or "").strip()[:maximum]


class ProfileStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as database:
            database.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    project TEXT NOT NULL DEFAULT '',
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    firmware TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    point_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            database.execute("CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name)")
            database.execute("CREATE INDEX IF NOT EXISTS idx_profiles_model ON profiles(manufacturer, model)")
            database.execute("CREATE INDEX IF NOT EXISTS idx_profiles_updated ON profiles(updated_at DESC)")

    def _normalize_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ValueError("Ungültiges Geräteprofil.")
        if payload.get("schema") != "hbtec-modbus-profile" or payload.get("schema_version") != 1:
            raise ValueError("Kein gültiges CKO-Modbusprofil.")
        profile = payload.get("profile")
        if not isinstance(profile, dict):
            raise ValueError("Profilinformationen fehlen.")
        points = payload.get("points")
        if not isinstance(points, list):
            raise ValueError("Datenpunktliste fehlt.")
        if len(points) > 1000:
            raise ValueError("Ein Profil darf höchstens 1000 Datenpunkte enthalten.")

        metadata = {
            "name": _clean_text(profile.get("name"), 160),
            "project": _clean_text(profile.get("project"), 160),
            "manufacturer": _clean_text(profile.get("manufacturer"), 160),
            "model": _clean_text(profile.get("model"), 160),
            "firmware": _clean_text(profile.get("firmware"), 120),
            "notes": _clean_text(profile.get("notes"), 2000),
            "point_count": len(points),
        }
        if not metadata["name"]:
            raise ValueError("Ein Profilname oder Produktname ist erforderlich.")
        normalized = json.loads(json.dumps(payload, ensure_ascii=False))
        normalized["profile"] = {**profile, **{key: metadata[key] for key in ("name", "project", "manufacturer", "model", "firmware", "notes")}}
        return normalized, metadata

    def save(self, payload: dict[str, Any], profile_id: str | None = None) -> dict[str, Any]:
        normalized, metadata = self._normalize_payload(payload)
        now = _utc_now()
        identifier = _clean_text(profile_id, 80) or str(uuid.uuid4())
        serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        with self._connect() as database:
            existing = database.execute("SELECT created_at FROM profiles WHERE id = ?", (identifier,)).fetchone()
            created_at = existing["created_at"] if existing else now
            database.execute(
                """
                INSERT INTO profiles (
                    id, name, project, manufacturer, model, firmware, notes,
                    payload_json, point_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    project = excluded.project,
                    manufacturer = excluded.manufacturer,
                    model = excluded.model,
                    firmware = excluded.firmware,
                    notes = excluded.notes,
                    payload_json = excluded.payload_json,
                    point_count = excluded.point_count,
                    updated_at = excluded.updated_at
                """,
                (
                    identifier,
                    metadata["name"],
                    metadata["project"],
                    metadata["manufacturer"],
                    metadata["model"],
                    metadata["firmware"],
                    metadata["notes"],
                    serialized,
                    metadata["point_count"],
                    created_at,
                    now,
                ),
            )
        return self.get(identifier)["metadata"]

    def list(self, query: str = "", limit: int = 100) -> list[dict[str, Any]]:
        query = _clean_text(query, 160)
        limit = max(1, min(int(limit), 200))
        parameters: list[Any] = []
        where = ""
        if query:
            term = f"%{query}%"
            where = "WHERE name LIKE ? OR project LIKE ? OR manufacturer LIKE ? OR model LIKE ? OR firmware LIKE ? OR notes LIKE ?"
            parameters.extend([term] * 6)
        parameters.append(limit)
        with self._connect() as database:
            rows = database.execute(
                f"""
                SELECT id, name, project, manufacturer, model, firmware, notes,
                       point_count, created_at, updated_at
                FROM profiles {where}
                ORDER BY updated_at DESC, manufacturer, model, name
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, profile_id: str) -> dict[str, Any]:
        with self._connect() as database:
            row = database.execute("SELECT * FROM profiles WHERE id = ?", (_clean_text(profile_id, 80),)).fetchone()
        if row is None:
            raise KeyError("Geräteprofil wurde nicht gefunden.")
        metadata = {key: row[key] for key in (
            "id", "name", "project", "manufacturer", "model", "firmware",
            "notes", "point_count", "created_at", "updated_at",
        )}
        return {"metadata": metadata, "payload": json.loads(row["payload_json"])}

    def delete(self, profile_id: str) -> bool:
        with self._connect() as database:
            cursor = database.execute("DELETE FROM profiles WHERE id = ?", (_clean_text(profile_id, 80),))
        return cursor.rowcount > 0

    def export_backup(self) -> dict[str, Any]:
        profiles = []
        for metadata in self.list(limit=200):
            profiles.append(self.get(metadata["id"]))
        return {
            "schema": BACKUP_SCHEMA,
            "schema_version": BACKUP_VERSION,
            "exported_at": _utc_now(),
            "profiles": profiles,
        }

    def import_backup(self, backup: dict[str, Any]) -> dict[str, int]:
        if not isinstance(backup, dict) or backup.get("schema") != BACKUP_SCHEMA or backup.get("schema_version") != BACKUP_VERSION:
            raise ValueError("Keine gültige CKO-Profilbibliothek.")
        records = backup.get("profiles")
        if not isinstance(records, list) or len(records) > 200:
            raise ValueError("Ungültige oder zu grosse Profilbibliothek.")
        created = updated = 0
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
                raise ValueError("Ein Eintrag der Profilbibliothek ist ungültig.")
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            identifier = _clean_text(metadata.get("id"), 80) or str(uuid.uuid4())
            try:
                self.get(identifier)
                updated += 1
            except KeyError:
                created += 1
            self.save(record["payload"], identifier)
        return {"created": created, "updated": updated, "total": created + updated}
