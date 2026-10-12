"""SunSpec-Erkennung: Kennung «SunS» suchen, Modelle durchlaufen und Werte mit Skalierungsfaktoren lesen.

SunSpec ist ein offener Standard für Wechselrichter, Zähler und Speicher (Fronius, SMA, SolarEdge, KACO …).
Die Modelldefinitionen stammen aus https://github.com/sunspec/models (Apache-2.0, siehe data/SUNSPEC-LICENSE.txt).
"""

from __future__ import annotations

import json
import struct
from functools import lru_cache
from pathlib import Path
from typing import Any

MARKER = [0x5375, 0x6E53]  # «SunS»
BASE_ADDRESSES = (40000, 0, 50000, 40001, 1, 50001)
END_MODEL = 0xFFFF
MAX_MODELS = 64
CHUNK = 120
MODELS_FILE = Path(__file__).resolve().parent / "data" / "sunspec_models.json"

# SunSpec-Typ → Inspector-Datentyp (SunSpec ist durchgehend Big-Endian: AB / ABCD / ABCDEFGH)
TYPE_MAP = {
    "int16": "int16", "uint16": "uint16", "count": "uint16", "acc16": "uint16", "enum16": "uint16",
    "bitfield16": "uint16", "sunssf": "int16", "int32": "int32", "uint32": "uint32", "acc32": "uint32",
    "enum32": "uint32", "bitfield32": "uint32", "ipaddr": "uint32", "int64": "int64", "uint64": "uint64",
    "acc64": "uint64", "float32": "float32", "float64": "float64", "string": "string",
}
ORDER = {1: "AB", 2: "ABCD", 4: "ABCDEFGH"}
# «nicht implementiert»-Kennwerte laut SunSpec
NOT_IMPLEMENTED = {"int16": 0x8000, "sunssf": 0x8000, "uint16": 0xFFFF, "count": 0xFFFF, "enum16": 0xFFFF,
                   "bitfield16": 0xFFFF, "int32": 0x80000000, "uint32": 0xFFFFFFFF, "enum32": 0xFFFFFFFF,
                   "bitfield32": 0xFFFFFFFF, "int64": 0x8000000000000000, "uint64": 0xFFFFFFFFFFFFFFFF}
MODEL_NAMES = {
    "1": "Geräteinformation", "101": "Wechselrichter einphasig", "102": "Wechselrichter zweiphasig",
    "103": "Wechselrichter dreiphasig", "111": "Wechselrichter einphasig (Float)", "112": "Wechselrichter zweiphasig (Float)",
    "113": "Wechselrichter dreiphasig (Float)", "120": "Typenschild", "121": "Grundeinstellungen", "122": "Messwerte & Status",
    "123": "Sofortsteuerung", "124": "Speicher", "160": "MPP-Tracker (Strings)", "201": "Zähler einphasig",
    "202": "Zähler zweiphasig", "203": "Zähler dreiphasig (Stern)", "204": "Zähler dreiphasig (Dreieck)",
    "211": "Zähler einphasig (Float)", "212": "Zähler zweiphasig (Float)", "213": "Zähler dreiphasig Stern (Float)",
    "214": "Zähler dreiphasig Dreieck (Float)", "701": "DER-Messwerte", "702": "DER-Kapazität", "802": "Batterie",
}


# Deutsche Bezeichnungen für die häufigsten SunSpec-Punkte (Name ohne Wiederholgruppen-Präfix)
GERMAN = {
    "Mn": "Hersteller", "Md": "Modell", "Opt": "Optionen", "Vr": "Firmware", "SN": "Seriennummer", "DA": "Geräteadresse",
    "A": "Strom gesamt", "AphA": "Strom L1", "AphB": "Strom L2", "AphC": "Strom L3",
    "PPVphAB": "Spannung L1-L2", "PPVphBC": "Spannung L2-L3", "PPVphCA": "Spannung L3-L1",
    "PhVphA": "Spannung L1-N", "PhVphB": "Spannung L2-N", "PhVphC": "Spannung L3-N", "PhV": "Spannung L-N Mittel",
    "PPV": "Spannung L-L Mittel", "W": "Wirkleistung gesamt", "WphA": "Wirkleistung L1", "WphB": "Wirkleistung L2",
    "WphC": "Wirkleistung L3", "Hz": "Frequenz", "VA": "Scheinleistung", "VAR": "Blindleistung", "VAr": "Blindleistung",
    "PF": "Leistungsfaktor", "WH": "Energie (Zählerstand)", "DCA": "DC-Strom", "DCV": "DC-Spannung", "DCW": "DC-Leistung",
    "TmpCab": "Gehäusetemperatur", "TmpSnk": "Kühlkörpertemperatur", "TmpTrns": "Trafotemperatur", "TmpOt": "Sonstige Temperatur",
    "St": "Betriebszustand", "StVnd": "Herstellerzustand", "Evt1": "Ereignisse 1", "Evt2": "Ereignisse 2",
    "TotWhExp": "Energie Einspeisung (Zählerstand)", "TotWhImp": "Energie Bezug (Zählerstand)",
    "TotVAhExp": "Scheinenergie Einspeisung", "TotVAhImp": "Scheinenergie Bezug",
    "SoC": "Ladezustand", "SoH": "Gesundheitszustand", "ChaState": "Ladezustand", "WChaMax": "Max. Ladeleistung",
    "WHRtg": "Nennkapazität", "DCSt": "DC-Status", "N": "Anzahl Module", "ID": "Modul-ID", "IDStr": "Modulname",
    "Tmp": "Temperatur", "DCWH": "DC-Energie (Zählerstand)",
}


def german_label(name: str, fallback: str) -> str:
    base = name.rsplit(".", 1)[-1]
    label = GERMAN.get(base)
    if not label:
        return fallback
    module = name.split(".", 1)[0] if "." in name else ""
    number = "".join(ch for ch in module if ch.isdigit())
    return f"{label} (Modul {number})" if number else label


@lru_cache(maxsize=1)
def models() -> dict[str, dict[str, Any]]:
    return json.loads(MODELS_FILE.read_text(encoding="utf-8"))["models"]


def _raw_int(registers: list[int]) -> int:
    value = 0
    for register in registers:
        value = (value << 16) | (register & 0xFFFF)
    return value


def decode_point(point: dict[str, Any], registers: list[int]) -> Any:
    """Rohwert eines SunSpec-Punkts; None, wenn nicht implementiert."""
    kind = point.get("type")
    if kind == "string":
        data = b"".join(register.to_bytes(2, "big") for register in registers)
        text = data.split(b"\x00", 1)[0].decode("latin-1").strip()
        return text or None
    if kind in ("float32", "float64"):
        fmt = ">f" if kind == "float32" else ">d"
        value = struct.unpack(fmt, b"".join(register.to_bytes(2, "big") for register in registers))[0]
        return None if value != value else value  # NaN = nicht implementiert
    raw = _raw_int(registers)
    if kind in ("acc16", "acc32", "acc64") and raw == 0:
        return None
    if NOT_IMPLEMENTED.get(kind) == raw:
        return None
    bits = 16 * len(registers)
    if kind in ("int16", "sunssf", "int32", "int64") and raw >= 1 << (bits - 1):
        raw -= 1 << bits
    return raw


def _flatten(group: dict[str, Any], start: int, length: int, values: dict[str, Any], prefix: str = "") -> list[dict[str, Any]]:
    """Punkte mit absoluter Registeradresse; Wiederholgruppen über Zählpunkt oder Restlänge."""
    points, offset = [], start
    for point in group.get("points", []):
        size = int(point.get("size", 1))
        points.append({**point, "name": f"{prefix}{point['name']}", "address": offset, "size": size})
        offset += size
    for child in group.get("groups", []):
        child_size = sum(int(p.get("size", 1)) for p in child.get("points", []))
        if not child_size:
            continue
        count = child.get("count", 1)
        if isinstance(count, str):
            count = int(values.get(f"{prefix}{count}") or 0)
        elif not count:
            count = max(0, (start + length - offset) // child_size)
        for index in range(min(int(count), 50)):
            label = f"{prefix}{child['name']}{index + 1}."
            points.extend(_flatten(child, offset, child_size, values, label))
            offset += child_size
    return points


def _read_block(read, address: int, count: int) -> list[int]:
    registers: list[int] = []
    while count > 0:
        size = min(CHUNK, count)
        response = read(address, size)
        if response is None or response.isError():
            raise ValueError(f"Register {address}–{address + size - 1} nicht lesbar")
        registers.extend(int(value) for value in response.registers[:size])
        address, count = address + size, count - size
    return registers


def find_base(read) -> int | None:
    for base in BASE_ADDRESSES:
        try:
            response = read(base, 2)
        except Exception:  # noqa: BLE001 – unbekannte Adresse ist normal
            continue
        if response is not None and not response.isError() and list(response.registers[:2]) == MARKER:
            return base
    return None


def scan(read) -> dict[str, Any]:
    """`read(address, count)` liest Holding-Register (FC03) über die gemeinsame Verbindung."""
    base = find_base(read)
    if base is None:
        return {"found": False, "base": None, "models": [],
                "hint": "Keine SunSpec-Kennung «SunS» an 40000, 0 oder 50000 gefunden. Das Gerät unterstützt SunSpec nicht, "
                        "SunSpec ist im Gerät nicht aktiviert (z. B. bei Fronius «Modbus TCP · SunSpec» einschalten) oder die Unit-ID ist falsch."}
    definitions = models()
    found, address = [], base + 2
    for _ in range(MAX_MODELS):
        header = _read_block(read, address, 2)
        model_id, length = header
        if model_id in (END_MODEL, 0):
            break
        key = str(model_id)
        entry = {"id": model_id, "address": address, "length": length, "name": MODEL_NAMES.get(key),
                 "label": None, "known": key in definitions, "points": []}
        if key in definitions:
            definition = definitions[key]
            entry["label"] = definition.get("label") or definition.get("name")
            try:
                block = _read_block(read, address, length + 2)
            except ValueError as error:
                entry["error"] = str(error)
                found.append(entry)
                address += 2 + length
                continue
            values: dict[str, Any] = {}
            flat = _flatten(definition, address, length + 2, values)
            # erst einfache Werte (für Zählpunkte und Skalierungsfaktoren), dann Wiederholgruppen neu auflösen
            for point in flat:
                rel = point["address"] - address
                if point["type"] != "pad" and rel + point["size"] <= len(block):
                    values[point["name"]] = decode_point(point, block[rel:rel + point["size"]])
            flat = _flatten(definition, address, length + 2, values)
            for point in flat:
                rel = point["address"] - address
                if point["type"] in ("pad", "eui48", "ipv6addr") or point["name"] in ("ID", "L") or rel + point["size"] > len(block):
                    continue
                raw = decode_point(point, block[rel:rel + point["size"]])
                values[point["name"]] = raw
                entry["points"].append(_describe(point, raw, flat, values))
        found.append(entry)
        address += 2 + length
    common = next((model for model in found if model["id"] == 1), None)
    info = {point["name"]: point["value"] for point in (common or {}).get("points", []) if point["name"] in ("Mn", "Md", "SN", "Vr", "Opt")}
    return {"found": True, "base": base, "models": found, "device": info}


def _describe(point: dict[str, Any], raw: Any, flat: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    data_type = TYPE_MAP.get(point["type"], "uint16")
    sf_name = point.get("sf")
    scale, sf_address, sf_value = 1, None, None
    if sf_name:
        prefix = point["name"].rsplit(".", 1)[0] + "." if "." in point["name"] else ""
        sf_point = next((p for p in flat if p["name"] in (f"{prefix}{sf_name}", sf_name)), None)
        if sf_point is not None:
            sf_address = sf_point["address"]
            sf_value = values.get(sf_point["name"])
        elif isinstance(sf_name, (int, float)):
            sf_value = int(sf_name)
        if isinstance(sf_value, int):
            scale = 10 ** sf_value
    value = raw
    if isinstance(raw, (int, float)) and point["type"] not in ("enum16", "enum32", "bitfield16", "bitfield32", "sunssf") and scale != 1:
        value = round(raw * scale, 6)
    return {
        "name": point["name"], "label": german_label(point["name"], point.get("label") or point["name"]), "address": point["address"],
        "size": point["size"], "sunspec_type": point["type"], "data_type": data_type,
        "order": "AB" if data_type == "string" else ORDER.get(point["size"], "AB"),
        "scale": scale, "scale_factor_address": sf_address, "units": point.get("units") or "",
        "value": value, "implemented": raw is not None,
    }
