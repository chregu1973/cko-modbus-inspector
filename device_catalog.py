from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_common import CONFIDENCE_LEVELS, QUANTITY_KINDS
from modbus_core import ORDERS, TYPE_COUNTS
from profile_store import default_database_path

ENTRY_SCHEMA = "hbtec-device-catalog-entry"
BACKUP_SCHEMA = "hbtec-device-catalog"
SCHEMA_VERSION = 1
MAX_POINTS = 300
MAX_ENTRIES_PER_IMPORT = 500
DEFAULT_DEVICE_TYPE = "sonstiges"

DEVICE_TYPE_LABELS = {
    "wechselrichter": "Wechselrichter",
    "energiezaehler": "Energiezähler",
    "waermepumpe": "Wärmepumpe",
    "waermemengenzaehler": "Wärmemengenzähler",
    "batteriespeicher": "Batteriespeicher",
    "ladestation": "Ladestation",
    "hlk": "Heizung/Lüftung/Klima",
    "kaelte": "Kälte-/Kühltechnik",
    "sensor": "Sensor",
    "gateway": "Gateway/Datenlogger",
    "sonstiges": "Sonstiges",
}
DEVICE_TYPES = tuple(DEVICE_TYPE_LABELS.keys())


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clean_text(value: Any, maximum: int = 500) -> str:
    return str(value or "").strip()[:maximum]


def _normalize_point(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    name = _clean_text(item.get("name"), 160)
    data_type = item.get("data_type")
    if not name or data_type not in TYPE_COUNTS:
        return None
    width = TYPE_COUNTS[data_type] * 2
    valid_orders = ORDERS.get(width, ())
    order = item.get("order")
    if order not in valid_orders:
        order = valid_orders[0] if valid_orders else ""
    quantity_kind = item.get("quantity_kind")
    if quantity_kind not in QUANTITY_KINDS:
        quantity_kind = "other"
    confidence = item.get("confidence")
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "mittel"
    function = item.get("function")
    if not isinstance(function, int) or function not in (1, 2, 3, 4):
        function = None
    address = item.get("address")
    if not isinstance(address, int) or address < 0:
        address = None
    scale = item.get("scale")
    if not isinstance(scale, (int, float)):
        scale = None
    scale_factor_address = item.get("scale_factor_address")
    if not isinstance(scale_factor_address, int) or scale_factor_address < 0:
        scale_factor_address = None
    scale_factor_type = _clean_text(item.get("scale_factor_type"), 40) if scale_factor_address is not None else ""
    return {
        "name": name,
        "quantity_kind": quantity_kind,
        "function": function,
        "address": address,
        "address_notes": _clean_text(item.get("address_notes"), 500),
        "data_type": data_type,
        "order": order,
        "scale": scale,
        "scale_factor_address": scale_factor_address,
        "scale_factor_type": scale_factor_type,
        "unit": _clean_text(item.get("unit"), 40),
        "confidence": confidence,
        "caveats": _clean_text(item.get("caveats"), 500),
    }


class DeviceCatalogStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as database, database:
            database.execute(
                """
                CREATE TABLE IF NOT EXISTS catalog_entries (
                    id TEXT PRIMARY KEY,
                    manufacturer TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    aliases TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    source_note TEXT NOT NULL DEFAULT '',
                    verified INTEGER NOT NULL DEFAULT 0,
                    device_type TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    point_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            columns = {row["name"] for row in database.execute("PRAGMA table_info(catalog_entries)").fetchall()}
            if "device_type" not in columns:
                database.execute("ALTER TABLE catalog_entries ADD COLUMN device_type TEXT NOT NULL DEFAULT ''")
            database.execute("CREATE INDEX IF NOT EXISTS idx_catalog_model ON catalog_entries(manufacturer, model)")
            database.execute("CREATE INDEX IF NOT EXISTS idx_catalog_updated ON catalog_entries(updated_at DESC)")
            database.execute("CREATE INDEX IF NOT EXISTS idx_catalog_type ON catalog_entries(device_type)")
            # Mitgelieferte Einträge, die schon einmal übernommen wurden (auch wenn sie später gelöscht wurden)
            database.execute(
                "CREATE TABLE IF NOT EXISTS catalog_seeded (seed_key TEXT PRIMARY KEY, seeded_at TEXT NOT NULL)"
            )

    def _normalize_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, dict) or payload.get("schema") != ENTRY_SCHEMA or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Kein gültiger CKO-Katalogeintrag.")
        manufacturer = _clean_text(payload.get("manufacturer"), 160)
        model = _clean_text(payload.get("model"), 160)
        if not manufacturer and not model:
            raise ValueError("Hersteller oder Modell ist erforderlich.")
        raw_points = payload.get("points")
        if not isinstance(raw_points, list):
            raise ValueError("Punkteliste fehlt.")
        points = [p for p in (_normalize_point(item) for item in raw_points[:MAX_POINTS]) if p is not None]

        device_type = _clean_text(payload.get("device_type"), 40).lower()
        if device_type not in DEVICE_TYPES:
            device_type = DEFAULT_DEVICE_TYPE

        metadata = {
            "manufacturer": manufacturer,
            "model": model,
            "aliases": _clean_text(payload.get("aliases"), 500),
            "notes": _clean_text(payload.get("notes"), 4000),
            "source_url": _clean_text(payload.get("source_url"), 500),
            "source_note": _clean_text(payload.get("source_note"), 500),
            "verified": bool(payload.get("verified")),
            "device_type": device_type,
            "point_count": len(points),
        }
        normalized = {
            "schema": ENTRY_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            **metadata,
            "points": points,
        }
        return normalized, metadata

    def save(self, payload: dict[str, Any], entry_id: str | None = None) -> dict[str, Any]:
        normalized, metadata = self._normalize_payload(payload)
        now = _utc_now()
        identifier = _clean_text(entry_id, 80) or str(uuid.uuid4())
        serialized = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        with closing(self._connect()) as database, database:
            existing = database.execute("SELECT created_at FROM catalog_entries WHERE id = ?", (identifier,)).fetchone()
            created_at = existing["created_at"] if existing else now
            database.execute(
                """
                INSERT INTO catalog_entries (
                    id, manufacturer, model, aliases, notes, source_url, source_note,
                    verified, device_type, payload_json, point_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    manufacturer = excluded.manufacturer,
                    model = excluded.model,
                    aliases = excluded.aliases,
                    notes = excluded.notes,
                    source_url = excluded.source_url,
                    source_note = excluded.source_note,
                    verified = excluded.verified,
                    device_type = excluded.device_type,
                    payload_json = excluded.payload_json,
                    point_count = excluded.point_count,
                    updated_at = excluded.updated_at
                """,
                (
                    identifier,
                    metadata["manufacturer"],
                    metadata["model"],
                    metadata["aliases"],
                    metadata["notes"],
                    metadata["source_url"],
                    metadata["source_note"],
                    int(metadata["verified"]),
                    metadata["device_type"],
                    serialized,
                    metadata["point_count"],
                    created_at,
                    now,
                ),
            )
        return self.get(identifier)["metadata"]

    def list(self, query: str = "", device_type: str = "", limit: int = 100, status: str = "") -> list[dict[str, Any]]:
        query = _clean_text(query, 160)
        device_type = _clean_text(device_type, 40).lower()
        status = _clean_text(status, 20).lower()
        limit = max(1, min(int(limit), 200))
        parameters: list[Any] = []
        conditions = []
        if query:
            term = f"%{query}%"
            conditions.append("(manufacturer LIKE ? OR model LIKE ? OR aliases LIKE ? OR notes LIKE ?)")
            parameters.extend([term] * 4)
        if device_type in DEVICE_TYPES:
            conditions.append("device_type = ?")
            parameters.append(device_type)
        if status == "incomplete":
            conditions.append("point_count = 0")
        elif status == "complete":
            conditions.append("point_count > 0")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        parameters.append(limit)
        with closing(self._connect()) as database, database:
            rows = database.execute(
                f"""
                SELECT id, manufacturer, model, aliases, notes, source_url, source_note,
                       verified, device_type, point_count, created_at, updated_at, payload_json
                FROM catalog_entries {where}
                ORDER BY (point_count = 0) DESC, updated_at DESC, manufacturer, model
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        results = []
        for row in rows:
            entry = dict(row)
            payload_json = entry.pop("payload_json")
            entry["points"] = json.loads(payload_json).get("points", [])
            results.append(entry)
        return results

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as database, database:
            row = database.execute(
                "SELECT COUNT(*) AS total, SUM(point_count = 0) AS incomplete FROM catalog_entries"
            ).fetchone()
        total = row["total"] or 0
        incomplete = row["incomplete"] or 0
        return {"total": total, "incomplete": incomplete, "complete": total - incomplete}

    def get(self, entry_id: str) -> dict[str, Any]:
        with closing(self._connect()) as database, database:
            row = database.execute(
                "SELECT * FROM catalog_entries WHERE id = ?", (_clean_text(entry_id, 80),)
            ).fetchone()
        if row is None:
            raise KeyError("Katalogeintrag wurde nicht gefunden.")
        metadata = {key: row[key] for key in (
            "id", "manufacturer", "model", "aliases", "notes", "source_url",
            "source_note", "verified", "device_type", "point_count", "created_at", "updated_at",
        )}
        return {"metadata": metadata, "payload": json.loads(row["payload_json"])}

    def delete(self, entry_id: str) -> bool:
        with closing(self._connect()) as database, database:
            cursor = database.execute("DELETE FROM catalog_entries WHERE id = ?", (_clean_text(entry_id, 80),))
        return cursor.rowcount > 0

    def seed_from_directory(self, directory: str | Path) -> int:
        """Mitgelieferte Katalogdateien übernehmen: nur fehlende Einträge, jeden nur einmal.

        Bestehende oder vom Benutzer geänderte Einträge bleiben unverändert; ein gelöschter
        mitgelieferter Eintrag kommt beim nächsten Start nicht zurück.
        """
        folder = Path(directory)
        if not folder.is_dir():
            return 0
        added = 0
        for file in sorted(folder.glob("*.hbdevicecatalog.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            entries = [data] if data.get("schema") == ENTRY_SCHEMA else data.get("entries") or []
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                manufacturer = _clean_text(entry.get("manufacturer"), 160)
                model = _clean_text(entry.get("model"), 160)
                key = f"{manufacturer.lower()}|{model.lower()}"
                with closing(self._connect()) as database, database:
                    seeded = database.execute("SELECT 1 FROM catalog_seeded WHERE seed_key = ?", (key,)).fetchone()
                if seeded:
                    continue
                if self._find_existing_id(manufacturer, model) is None:
                    try:
                        self.save(entry)
                    except ValueError:
                        continue
                    added += 1
                with closing(self._connect()) as database, database:
                    database.execute(
                        "INSERT OR IGNORE INTO catalog_seeded (seed_key, seeded_at) VALUES (?, ?)", (key, _utc_now())
                    )
        return added

    def _find_existing_id(self, manufacturer: str, model: str) -> str | None:
        with closing(self._connect()) as database, database:
            row = database.execute(
                "SELECT id FROM catalog_entries WHERE lower(manufacturer) = lower(?) AND lower(model) = lower(?)",
                (manufacturer, model),
            ).fetchone()
        return row["id"] if row else None

    def import_payload(self, data: Any) -> dict[str, int]:
        if not isinstance(data, dict):
            raise ValueError("Ungültige Katalog-Datei.")
        schema = data.get("schema")
        if schema == ENTRY_SCHEMA:
            entries = [data]
        elif schema == BACKUP_SCHEMA:
            entries = data.get("entries")
            if not isinstance(entries, list):
                raise ValueError("Katalog-Sicherung enthält keine Einträge.")
        else:
            raise ValueError("Unbekanntes Katalog-Dateiformat.")
        if len(entries) > MAX_ENTRIES_PER_IMPORT:
            raise ValueError("Zu viele Einträge in dieser Katalog-Datei.")

        created = updated = 0
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Ein Katalogeintrag ist ungültig.")
            manufacturer = _clean_text(entry.get("manufacturer"), 160)
            model = _clean_text(entry.get("model"), 160)
            existing_id = self._find_existing_id(manufacturer, model)
            self.save(entry, existing_id)
            if existing_id:
                updated += 1
            else:
                created += 1
        return {"created": created, "updated": updated, "total": created + updated}
