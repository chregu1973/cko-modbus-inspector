"""Zählerliste: geprüfte Datenpunkte mit Verbindung, KNX-DPT-Vorschlag und Plausibilitätshinweisen.

Die Liste dient als Übergabe an die Gateway-Konfiguration (KNX-Modbus-Gateway, Node-RED, Visu) und als
Inbetriebnahme-Protokoll. Der DPT ist ein Vorschlag nach Einheit und Messgrösse; massgebend ist das
Gateway bzw. die Visualisierung.
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any

# Einheit → (DPT, Bezeichnung, Hinweis)
UNIT_DPTS: dict[str, tuple[str, str, str]] = {
    "w": ("14.056", "Leistung (W), 4 Byte Gleitkomma", ""),
    "kw": ("9.024", "Leistung (kW), 2 Byte Gleitkomma", "Alternativ 14.056 in W (Faktor × 1000)"),
    "wh": ("13.010", "Wirkenergie (Wh), 4 Byte ganzzahlig", ""),
    "kwh": ("13.013", "Wirkenergie (kWh), 4 Byte ganzzahlig", "Ganzzahlig – für Nachkommastellen 13.010 in Wh (Faktor × 1000)"),
    "mwh": ("13.013", "Wirkenergie (kWh), 4 Byte ganzzahlig", "Faktor × 1000 auf kWh umrechnen"),
    "varh": ("13.012", "Blindenergie (varh), 4 Byte ganzzahlig", ""),
    "kvarh": ("13.015", "Blindenergie (kvarh), 4 Byte ganzzahlig", ""),
    "vah": ("13.011", "Scheinenergie (VAh), 4 Byte ganzzahlig", ""),
    "kvah": ("13.014", "Scheinenergie (kVAh), 4 Byte ganzzahlig", ""),
    "var": ("14.056", "Leistung, 4 Byte Gleitkomma", "Kein eigener DPT für Blindleistung – Einheit var in der Bezeichnung"),
    "kvar": ("9.024", "Leistung (kW), 2 Byte Gleitkomma", "Kein eigener DPT für Blindleistung"),
    "va": ("14.056", "Leistung, 4 Byte Gleitkomma", "Kein eigener DPT für Scheinleistung – Einheit VA in der Bezeichnung"),
    "kva": ("9.024", "Leistung (kW), 2 Byte Gleitkomma", "Kein eigener DPT für Scheinleistung"),
    "v": ("14.027", "Elektrische Spannung (V), 4 Byte Gleitkomma", ""),
    "mv": ("9.020", "Spannung (mV), 2 Byte Gleitkomma", ""),
    "a": ("14.019", "Elektrischer Strom (A), 4 Byte Gleitkomma", ""),
    "ma": ("9.021", "Strom (mA), 2 Byte Gleitkomma", ""),
    "hz": ("14.033", "Frequenz (Hz), 4 Byte Gleitkomma", ""),
    "°c": ("9.001", "Temperatur (°C), 2 Byte Gleitkomma", ""),
    "%": ("5.001", "Prozent (0–100 %), 1 Byte", "Werte über 100 % oder mit Nachkommastellen: 14.xxx bzw. 9.007"),
    "m³": ("14.076", "Volumen (m³), 4 Byte Gleitkomma", ""),
    "m3": ("14.076", "Volumen (m³), 4 Byte Gleitkomma", ""),
    "l/h": ("9.025", "Durchfluss (l/h), 2 Byte Gleitkomma", ""),
    "m³/h": ("13.002", "Durchfluss (m³/h), 4 Byte ganzzahlig", "Für Nachkommastellen 14.077 (m³/s) mit Umrechnung"),
    "bar": ("9.006", "Druck (Pa), 2 Byte Gleitkomma", "Faktor × 100 000 auf Pa umrechnen"),
}
POWER_FACTOR_WORDS = ("leistungsfaktor", "cos", "power factor", "pf")

# Messgrösse → erwarteter Bereich für Plausibilitätshinweise (in der angegebenen Einheit)
PLAUSIBLE = {
    "v": (0, 1000, "Spannung"),
    "hz": (45, 65, "Frequenz"),
    "a": (-6300, 6300, "Strom"),
    "w": (-5_000_000, 5_000_000, "Leistung"),
    "kw": (-5000, 5000, "Leistung"),
}


def knx_dpt(point: dict[str, Any]) -> dict[str, str]:
    if int(point.get("function", 3) or 3) in (1, 2) or point.get("data_type") == "bool":
        return {"dpt": "1.001", "label": "Schalten (1 Bit)", "note": ""}
    if point.get("data_type") == "string":
        return {"dpt": "16.001", "label": "Text (14 Zeichen)", "note": "Längere Texte werden gekürzt"}
    name = str(point.get("name", "")).lower()
    unit = str(point.get("unit", "")).strip().lower()
    if any(word in name for word in POWER_FACTOR_WORDS) and unit in ("", "-", "cos φ", "cosφ"):
        return {"dpt": "14.057", "label": "Leistungsfaktor cos φ, 4 Byte Gleitkomma", "note": ""}
    if unit in UNIT_DPTS:
        dpt, label, note = UNIT_DPTS[unit]
        return {"dpt": dpt, "label": label, "note": note}
    if point.get("quantity_kind") == "temperature":
        return {"dpt": "9.001", "label": "Temperatur (°C), 2 Byte Gleitkomma", "note": ""}
    return {"dpt": "14.xxx", "label": "4 Byte Gleitkomma", "note": "Untertyp passend zur Einheit wählen"}


def plausibility(point: dict[str, Any], value: Any) -> list[str]:
    """Einfache Hinweise auf falsche Skalierung, Datentyp oder Phasenlage – kein Beweis, nur Anlass zur Prüfung."""
    if value is None or isinstance(value, (bool, str)):
        return []
    try:
        number = float(value)
    except (TypeError, ValueError):
        return []
    if math.isnan(number) or math.isinf(number):
        return ["Kein gültiger Zahlenwert (NaN/∞) – Datentyp oder Byte-Reihenfolge prüfen."]
    name = str(point.get("name", "")).lower()
    unit = str(point.get("unit", "")).strip().lower()
    hints: list[str] = []
    if unit in PLAUSIBLE:
        low, high, label = PLAUSIBLE[unit]
        if not low <= number <= high:
            hints.append(f"{label} {number:g} {point.get('unit')} ausserhalb des üblichen Bereichs – Faktor oder Datentyp prüfen.")
    if unit == "v" and 0 < number < 50 and "dc" not in name:
        hints.append("Spannung sehr tief – fehlt ein Faktor (z. B. × 10) oder ist es ein Wandlerwert?")
    if unit == "v" and 300 < number < 500 and not any(word in name for word in ("l1-l2", "l2-l3", "l3-l1", "aussenleiter", "verkettet", "ll")):
        hints.append("Spannung ≈ 400 V: verkettete Spannung (L-L) statt L-N? Bezeichnung prüfen.")
    if unit in ("kwh", "wh", "mwh", "kvarh", "varh") and number < 0:
        hints.append("Negativer Zählerstand – Datentyp (signed/unsigned) oder Byte-Reihenfolge prüfen.")
    if any(word in name for word in POWER_FACTOR_WORDS) and unit in ("", "-") and abs(number) > 1.0001:
        hints.append("Leistungsfaktor grösser als 1 – Faktor (z. B. × 0,001) fehlt.")
    if unit in ("w", "kw") and number < 0 and any(word in name for word in ("bezug", "verbrauch", "last")):
        hints.append("Negative Leistung bei einem Verbraucher – Wandler/Zähler verkehrt eingebaut, Phasen vertauscht "
                     "oder Vorzeichenkonvention des Zählers (Einspeisung negativ) prüfen.")
    return hints


def _connection_text(connection: dict[str, Any]) -> str:
    transport = connection.get("transport")
    if transport == "rtu_serial":
        return f"RTU {connection.get('serial_port', '')} · {connection.get('baudrate', '')} Baud {connection.get('data_format', '')}"
    kind = "RTU über TCP" if transport == "rtu_tcp" else "Modbus TCP"
    return f"{kind} {connection.get('host', '')}:{connection.get('port', 502)}"


def build_rows(points: list[dict[str, Any]], connection: dict[str, Any], values: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if not points:
        raise ValueError("Noch keine Datenpunkte für die Zählerliste vorhanden.")
    values = values or {}
    rows = []
    for point in points:
        dpt = knx_dpt(point)
        value = values.get(str(point.get("id", "")))
        function = int(point.get("function", 3) or 3)
        rows.append({
            "name": str(point.get("name") or f"Register {point.get('address')}"),
            "connection": _connection_text(connection),
            "unit_id": point.get("unit_id", 1),
            "function": f"FC{function:02d}",
            "address": point.get("address", 0),
            "data_type": str(point.get("data_type", "")).upper(),
            "order": point.get("order") or ("BIT" if function in (1, 2) else ""),
            "scale": point.get("scale", 1),
            "offset": point.get("offset", 0),
            "unit": point.get("unit", ""),
            "value": value,
            "dpt": dpt["dpt"],
            "dpt_label": dpt["label"],
            "dpt_note": dpt["note"],
            "hints": plausibility(point, value),
        })
    return rows


CSV_HEADER = ["Bezeichnung", "Verbindung", "Unit-ID", "Funktion", "Register", "Datentyp", "Reihenfolge", "Faktor",
              "Offset", "Einheit", "Letzter Wert", "KNX-DPT (Vorschlag)", "DPT-Beschreibung", "Hinweis DPT", "Plausibilität",
              "Gruppenadresse", "Raum / Verbraucher"]


def build_csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    writer.writerow(CSV_HEADER)
    for row in rows:
        value = row["value"]
        writer.writerow([
            row["name"], row["connection"], row["unit_id"], row["function"], row["address"], row["data_type"], row["order"],
            str(row["scale"]).replace(".", ","), str(row["offset"]).replace(".", ","), row["unit"],
            "" if value is None else str(value).replace(".", ","),
            row["dpt"], row["dpt_label"], row["dpt_note"], " ".join(row["hints"]), "", "",
        ])
    return "﻿" + buffer.getvalue()
