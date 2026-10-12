"""Loxone-Modbus-Vorlagen (XML aus Loxone Config / Loxone Library) ins Geräte-Nachschlagewerk übernehmen.

Die Vorlagen der Loxone Library gehören ihren Erstellern und haben keine offene Lizenz. Sie werden daher nicht
mitgeliefert – der Benutzer lädt sie selbst herunter und importiert sie in sein lokales Nachschlagewerk.

Format: <Modbus Title="…"> bzw. <ModbusServer …> mit <ModbusCmd Title ModbusAddress ModbusCmd ModbusDataType
SourceValLow/High DestValLow/High Unit …>. ModbusDataType: 0 UInt16, 1 Int16, 2 UInt32, 3 Int32, 4 Float32,
6 UInt64, 7 Int64, 8 Float64; +32 = Register-Reihenfolge getauscht, +128 = Byte-Reihenfolge getauscht.
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

BASE_TYPES = {0: "uint16", 1: "int16", 2: "uint32", 3: "int32", 4: "float32", 6: "uint64", 7: "int64", 8: "float64"}
WORDS = {"uint16": 1, "int16": 1, "uint32": 2, "int32": 2, "float32": 2, "uint64": 4, "int64": 4, "float64": 4}
ORDERS = {  # (Register getauscht, Bytes getauscht) → Reihenfolge
    1: {(False, False): "AB", (True, False): "AB", (False, True): "BA", (True, True): "BA"},
    2: {(False, False): "ABCD", (True, False): "CDAB", (False, True): "BADC", (True, True): "DCBA"},
    4: {(False, False): "ABCDEFGH", (True, False): "GHEFCDAB", (False, True): "BADCFEHG", (True, True): "HGFEDCBA"},
}
READ_FUNCTIONS = {1, 2, 3, 4}
WRITE_TO_READ = {5: 1, 15: 1, 6: 3, 16: 3}
UNIT_TAG = re.compile(r"<v(?:\.\d+)?>")
KIND_BY_UNIT = {"w": "power", "kw": "power", "wh": "energy", "kwh": "energy", "mwh": "energy", "v": "voltage",
                "a": "current", "hz": "frequency", "°c": "temperature", "°": "temperature", "%": "percent"}


class LoxoneImportError(ValueError):
    pass


def _number(value: Any, default: float) -> float:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def _unit(raw: str) -> str:
    return UNIT_TAG.sub("", raw or "").strip()


def convert(xml_text: str, filename: str = "") -> dict[str, Any]:
    if re.search(r"<!DOCTYPE|<!ENTITY", xml_text[:4096], re.IGNORECASE):
        raise LoxoneImportError("XML mit DOCTYPE/ENTITY wird aus Sicherheitsgründen nicht gelesen.")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as error:
        raise LoxoneImportError(f"Keine gültige XML-Datei: {error}") from error
    commands = root.findall(".//ModbusCmd")
    if not commands:
        raise LoxoneImportError("Keine Loxone-Modbus-Vorlage: es fehlen <ModbusCmd>-Einträge.")
    title = (root.get("Title") or filename.rsplit(".", 1)[0] or "Loxone-Vorlage").strip()
    manufacturer, _, model = title.partition(" ")
    if not model:
        manufacturer, model = "Loxone-Vorlage", title
    points, skipped = [], 0
    for command in commands:
        name = (command.get("Title") or "").strip()
        function = int(_number(command.get("ModbusCmd"), 3))
        writable = function in WRITE_TO_READ
        function = WRITE_TO_READ.get(function, function)
        address = command.get("ModbusAddress")
        if not name or function not in READ_FUNCTIONS or address is None or not str(address).isdigit():
            skipped += 1
            continue
        raw_type = int(_number(command.get("ModbusDataType"), 0))
        data_type = "bool" if function in (1, 2) else BASE_TYPES.get(raw_type & 0x0F)
        if data_type is None:
            skipped += 1
            continue
        order = "" if data_type == "bool" else ORDERS[WORDS[data_type]][(bool(raw_type & 32), bool(raw_type & 128))]
        source_low, source_high = _number(command.get("SourceValLow"), 0), _number(command.get("SourceValHigh"), 100)
        dest_low, dest_high = _number(command.get("DestValLow"), 0), _number(command.get("DestValHigh"), 100)
        span = source_high - source_low
        scale = (dest_high - dest_low) / span if span else 1.0
        offset = dest_low - source_low * scale
        unit = _unit(command.get("Unit", ""))
        caveats = []
        if offset:
            caveats.append(f"Loxone-Korrektur mit Offset {offset:g}")
        if writable:
            caveats.append("in der Vorlage als Schreibbefehl hinterlegt – Lesbarkeit prüfen")
        if command.get("HintText"):
            caveats.append(command.get("HintText").strip())
        points.append({
            "name": name, "quantity_kind": KIND_BY_UNIT.get(unit.lower(), "other"), "function": function,
            "address": int(address), "data_type": data_type, "order": order, "scale": round(scale, 10),
            "unit": unit, "confidence": "mittel", "caveats": "; ".join(caveats),
        })
    if not points:
        raise LoxoneImportError("Die Vorlage enthält keine übernehmbaren Lese-Datenpunkte.")
    connection = []
    for attribute, label in (("Baudrate", "Baudrate"), ("Stopbits", "Stoppbits"), ("Parity", "Parität"), ("Port", "Port")):
        if root.get(attribute):
            connection.append(f"{label} {root.get(attribute)}")
    notes = (f"Aus Loxone-Vorlage «{filename or title}» importiert ({len(points)} Datenpunkte"
             f"{f', {skipped} ausgelassen' if skipped else ''}). Adressen wie in der Vorlage (Loxone zählt ab 0)."
             f"{' Verbindung laut Vorlage: ' + ', '.join(connection) + '.' if connection else ''}")
    return {
        "schema": "hbtec-device-catalog-entry", "schema_version": 1,
        "manufacturer": manufacturer, "model": model, "device_type": "sonstiges", "aliases": "",
        "notes": notes, "source_url": "", "source_note": "Loxone-Vorlage (lokal importiert, nicht weitergeben ohne Erlaubnis des Erstellers)",
        "verified": False, "points": points,
    }
