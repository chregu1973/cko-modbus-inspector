"""Geprüfte Datenpunkte als YAML für die generische Modbus-Integration von Home Assistant.

Erzeugt einen `modbus:`-Hub mit `sensors` (FC03/FC04) und `binary_sensors` (FC01/FC02). Begriffe wie in
Home Assistant: `device_address` ist die Unit-ID (frühere Bezeichnung `slave`).
"""

from __future__ import annotations

import json
import re
from decimal import Decimal
from typing import Any

# Byte-/Word-Reihenfolge des Inspectors → `swap` in Home Assistant
SWAP = {
    "AB": "none", "BA": "byte",
    "ABCD": "none", "BADC": "byte", "CDAB": "word", "DCBA": "word_byte",
    "ABCDEFGH": "none", "BADCFEHG": "byte", "GHEFCDAB": "word", "HGFEDCBA": "word_byte",
}
REGISTER_TYPES = {3: "holding", 4: "input"}
BIT_TYPES = {1: "coil", 2: "discrete_input"}
SERIAL_FORMATS = {"8N1": (8, "N", 1), "8E1": (8, "E", 1), "8O1": (8, "O", 1), "8N2": (8, "N", 2)}
HA_DATA_TYPES = {"uint16", "int16", "float16", "uint32", "int32", "float32", "uint64", "int64", "float64", "string"}


def _quote(value: Any) -> str:
    """YAML-sicherer Skalar (JSON-Strings sind gültiges YAML)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = repr(float(value)) if isinstance(value, float) else str(value)
        return text[:-2] if text.endswith(".0") else text
    return json.dumps(str(value), ensure_ascii=False)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower().translate(str.maketrans("äöüß", "aous"))).strip("_")
    return slug or "modbus"


def _precision(point: dict[str, Any]) -> int | None:
    scale = point.get("scale", 1)
    try:
        exponent = Decimal(str(float(scale))).normalize().as_tuple().exponent
    except (TypeError, ValueError, ArithmeticError):
        exponent = 0
    decimals = max(0, -int(exponent))
    if str(point.get("data_type", "")).startswith("float"):
        return max(decimals, 2)
    return decimals or None


def build_yaml(points: list[dict[str, Any]], connection: dict[str, Any], hub_name: str = "",
               scan_interval: int = 15) -> str:
    if not points:
        raise ValueError("Keine Datenpunkte für den Export vorhanden.")
    timeout = max(1, round(int(connection.get("timeout_ms", 3000)) / 1000))
    header = [
        "# Erzeugt mit dem CKO Modbus Inspector – geprüfte Datenpunkte für die Home-Assistant-Integration «Modbus».",
        "# In configuration.yaml einfügen (oder per !include). device_address = Unit-ID (ältere Versionen: slave).",
        "modbus:",
    ]
    if connection.get("transport") == "rtu_serial":
        port_name = str(connection.get("serial_port", "")).strip()
        if not port_name:
            raise ValueError("Für den Export fehlt die serielle Schnittstelle.")
        data_format = str(connection.get("data_format", "8N1")).upper()
        if data_format not in SERIAL_FORMATS:
            raise ValueError("Unbekanntes Datenformat der seriellen Verbindung.")
        bytesize, parity, stopbits = SERIAL_FORMATS[data_format]
        hub = hub_name.strip() or f"Modbus RTU {port_name}"
        lines = header + [
            f"  - name: {_quote(hub)}",
            "    type: serial",
            "    method: rtu",
            "    # Am Home-Assistant-Rechner heisst die Schnittstelle meist /dev/ttyUSB0 oder /dev/serial/by-id/…",
            f"    port: {_quote(port_name)}",
            f"    baudrate: {int(connection.get('baudrate', 9600))}",
            f"    bytesize: {bytesize}",
            f"    parity: {parity}",
            f"    stopbits: {stopbits}",
            f"    timeout: {timeout}",
        ]
    else:
        host = str(connection.get("host", "")).strip()
        if not host:
            raise ValueError("Für den Export fehlt die IP-Adresse des Geräts.")
        hub = hub_name.strip() or f"Modbus {host}"
        transport = "rtuovertcp" if connection.get("transport") == "rtu_tcp" else "tcp"
        lines = header + [
            f"  - name: {_quote(hub)}",
            f"    type: {transport}",
            f"    host: {_quote(host)}",
            f"    port: {int(connection.get('port', 502))}",
            f"    timeout: {timeout}",
        ]
    wait_ms = int(connection.get("wait_ms", 0) or 0)
    if wait_ms:
        lines.append(f"    message_wait_milliseconds: {wait_ms}")

    sensors, binaries, skipped = [], [], []
    used_ids: set[str] = set()
    for point in points:
        function = int(point.get("function", 3))
        name = str(point.get("name") or f"Register {point.get('address')}").strip()
        unique = f"{_slug(hub)}_{_slug(name)}"
        while unique in used_ids:
            unique += "_2"
        used_ids.add(unique)
        common = [
            f"      - name: {_quote(name)}",
            f"        unique_id: {_quote(unique)}",
            f"        device_address: {int(point.get('unit_id', 1))}",
            f"        address: {int(point.get('address', 0))}",
        ]
        if function in BIT_TYPES:
            binaries.append(common + [f"        input_type: {BIT_TYPES[function]}", f"        scan_interval: {scan_interval}"])
            continue
        data_type = str(point.get("data_type", "uint16")).lower()
        if data_type not in HA_DATA_TYPES:
            skipped.append(name)
            continue
        entry = common + [f"        input_type: {REGISTER_TYPES.get(function, 'holding')}", f"        data_type: {data_type}"]
        if data_type == "string":
            entry.append(f"        count: {int(point.get('length', 1))}")
        else:
            swap = SWAP.get(str(point.get("order") or "").upper(), "none")
            if swap != "none":
                entry.append(f"        swap: {swap}")
            scale, offset = float(point.get("scale", 1) or 1), float(point.get("offset", 0) or 0)
            if scale != 1:
                entry.append(f"        scale: {_quote(scale)}")
            if offset:
                entry.append(f"        offset: {_quote(offset)}")
            precision = _precision(point)
            if precision is not None:
                entry.append(f"        precision: {precision}")
            if point.get("unit"):
                entry.append(f"        unit_of_measurement: {_quote(point['unit'])}")
        entry.append(f"        scan_interval: {scan_interval}")
        sensors.append(entry)

    if sensors:
        lines.append("    sensors:")
        lines.extend(line for entry in sensors for line in entry)
    if binaries:
        lines.append("    binary_sensors:")
        lines.extend(line for entry in binaries for line in entry)
    if skipped:
        lines.append(f"# Nicht exportiert (Datentyp ohne Entsprechung in Home Assistant): {', '.join(skipped)}")
    return "\n".join(lines) + "\n"
