"""Gemeinsame Modbus-Verbindungen – eine Verbindung pro Ziel, Anfragen nacheinander.

Viele Geräte nehmen nur wenige gleichzeitige Modbus-Sitzungen an. Decoder, Live-Monitor, Register-Finder,
Unit-Scan und Schreiben nutzen deshalb dieselbe offene Verbindung (wie die gemeinsamen Verbindungen in
Home Assistant). Nach einem Abbruch wird beim nächsten Bedarf wieder verbunden, nach Fehlschlägen mit
wachsendem Abstand; unbenutzte Verbindungen schliessen nach einer Leerlaufzeit.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

IDLE_CLOSE_SECONDS = 60
BACKOFF_STEPS = (1, 2, 5, 10, 30)


class ConnectionUnavailable(Exception):
    """Verbindung kann gerade nicht aufgebaut werden (Gerät erreichbar? Sitzungslimit?)."""


@dataclass
class _Entry:
    key: tuple
    label: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    client: Any = None
    connected_since: float | None = None
    last_used: float = 0.0
    last_request: float = 0.0
    requests: int = 0
    errors: int = 0
    connects: int = 0
    failed_connects: int = 0
    next_attempt: float = 0.0
    last_error: str = ""
    last_error_at: float | None = None
    users: dict[str, float] = field(default_factory=dict)
    settings: tuple = ()


class ConnectionPool:
    def __init__(self, factory: Callable[[Any], Any], clock: Callable[[], float] = time.monotonic):
        self._factory = factory
        self._clock = clock
        self._entries: dict[tuple, _Entry] = {}
        self._guard = threading.Lock()

    @staticmethod
    def key_for(target: Any) -> tuple:
        return (target.host, target.port, target.transport)

    def _entry(self, target: Any) -> _Entry:
        key = self.key_for(target)
        with self._guard:
            entry = self._entries.get(key)
            if entry is None:
                label = f"{target.host}:{target.port} · {'RTU über TCP' if target.transport == 'rtu_tcp' else 'Modbus TCP'}"
                entry = self._entries[key] = _Entry(key=key, label=label)
            return entry

    def _close(self, entry: _Entry) -> None:
        if entry.client is not None:
            try:
                entry.client.close()
            except Exception:  # noqa: BLE001 – Schliessen darf nie scheitern
                pass
        entry.client = None
        entry.connected_since = None

    def close_idle(self) -> None:
        now = self._clock()
        with self._guard:
            entries = list(self._entries.values())
        for entry in entries:
            if entry.client is not None and now - entry.last_used > IDLE_CLOSE_SECONDS and entry.lock.acquire(blocking=False):
                try:
                    self._close(entry)
                finally:
                    entry.lock.release()

    def close_all(self) -> None:
        with self._guard:
            entries = list(self._entries.values())
        for entry in entries:
            with entry.lock:
                self._close(entry)

    @contextmanager
    def session(self, target: Any, user: str = "Abfrage", wait_ms: int = 0, fresh: bool = False):
        """Exklusiven Zugriff auf die gemeinsame Verbindung; fresh=True baut sie vorher neu auf."""
        self.close_idle()
        entry = self._entry(target)
        with entry.lock:
            now = self._clock()
            entry.users[user] = now
            settings = (getattr(target, "timeout", None),)
            if fresh or (entry.client is not None and entry.settings != settings):
                self._close(entry)  # neu aufbauen statt zweite Sitzung zu öffnen
            entry.settings = settings
            if entry.client is None:
                if now < entry.next_attempt:
                    wait = int(entry.next_attempt - now + 0.999)
                    raise ConnectionUnavailable(
                        f"Keine Verbindung zu {entry.label} – nächster Versuch in {wait} s. {entry.last_error}".strip())
                client = self._factory(target)
                try:
                    ok = client.connect()
                except OSError as error:
                    ok, entry.last_error = False, str(error)
                if not ok:
                    entry.failed_connects += 1
                    step = BACKOFF_STEPS[min(entry.failed_connects - 1, len(BACKOFF_STEPS) - 1)]
                    entry.next_attempt = now + step
                    entry.last_error = (
                        "Verbindung abgelehnt oder nicht erreichbar. Nimmt das Gerät keine weitere Sitzung an, "
                        "laufen evtl. Home Assistant, Node-RED oder die Visu parallel – kurz stoppen und erneut versuchen."
                    )
                    entry.last_error_at = self._clock()
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
                    raise ConnectionUnavailable(f"Keine TCP-Verbindung zu {entry.label}. {entry.last_error}")
                entry.client, entry.connected_since = client, now
                entry.connects += 1
                entry.failed_connects, entry.next_attempt = 0, 0.0
            handle = _Handle(self, entry, wait_ms)
            try:
                yield handle
            finally:
                entry.last_used = self._clock()

    def reset(self) -> None:
        """Alle Verbindungen schliessen und vergessen (Tests, Programmende)."""
        self.close_all()
        with self._guard:
            self._entries.clear()

    def status(self) -> list[dict[str, Any]]:
        now = self._clock()
        with self._guard:
            entries = list(self._entries.values())
        rows = []
        for entry in entries:
            rows.append({
                "connection": entry.label,
                "open": entry.client is not None,
                "connected_for_s": round(now - entry.connected_since) if entry.connected_since else None,
                "requests": entry.requests,
                "errors": entry.errors,
                "reconnects": max(0, entry.connects - 1),
                "retry_in_s": max(0, round(entry.next_attempt - now)) if entry.next_attempt > now else 0,
                "last_error": entry.last_error,
                "last_error_ago_s": round(now - entry.last_error_at) if entry.last_error_at else None,
                "users": sorted(user for user, seen in entry.users.items() if now - seen < 120),
            })
        return rows


def _is_connection_error(error: Exception) -> bool:
    # pymodbus: ConnectionException / ModbusIOException (Timeout) – ohne harte Abhängigkeit vom Paket
    return isinstance(error, OSError) or type(error).__name__ in {"ConnectionException", "ModbusIOException"}


class _Handle:
    """Führt Anfragen auf der gemeinsamen Verbindung aus; bei Verbindungsfehlern wird sie verworfen."""

    def __init__(self, pool: ConnectionPool, entry: _Entry, wait_ms: int):
        self._pool, self._entry, self._wait = pool, entry, max(0, wait_ms) / 1000

    @property
    def client(self):
        return self._entry.client

    def call(self, function: Callable[[Any], Any]):
        entry = self._entry
        if entry.client is None:
            raise ConnectionUnavailable(f"Verbindung zu {entry.label} wurde getrennt.")
        if self._wait:
            pause = self._wait - (self._pool._clock() - entry.last_request)
            if pause > 0:
                time.sleep(pause)
        try:
            result = function(entry.client)
        except Exception as error:
            entry.errors += 1
            entry.last_error_at = self._pool._clock()
            if _is_connection_error(error):
                entry.last_error = f"Verbindung unterbrochen oder keine Antwort: {error}"
                self._pool._close(entry)  # beim nächsten Bedarf neu verbinden
            else:
                entry.last_error = str(error)
            raise
        finally:
            entry.requests += 1
            entry.last_request = self._pool._clock()
        if result is None or (hasattr(result, "isError") and result.isError()):
            entry.errors += 1
        return result
