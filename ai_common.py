from __future__ import annotations

from typing import Any

from modbus_core import InspectorError, ORDERS, QUANTITY_TYPE_SCORES, TYPE_COUNTS

MAX_SUGGESTIONS = 12
QUANTITY_KINDS = tuple(QUANTITY_TYPE_SCORES.keys()) + ("other",)
DATA_TYPES = tuple(TYPE_COUNTS.keys())
CONFIDENCE_LEVELS = ("hoch", "mittel", "niedrig")


def research_prompt(manufacturer: str, model: str, firmware: str, quantity: str | None) -> str:
    device_desc = ", ".join(
        part for part in (
            f"Hersteller: {manufacturer}" if manufacturer else "",
            f"Modell: {model}" if model else "",
            f"Firmware: {firmware}" if firmware else "",
        )
        if part
    )
    if quantity:
        task = (
            f"Suche gezielt nach dem Modbus-Register für die Grösse \"{quantity}\" bei diesem Gerät. "
            "Gib nur die 1-3 wahrscheinlichsten Register für genau diese Grösse zurück."
        )
    else:
        task = (
            "Suche nach den wichtigsten, typischerweise für eine Visualisierung/SCADA relevanten "
            "Modbus-Datenpunkten dieses Geräts (z. B. Leistung, Spannung, Strom, Energie, Frequenz, "
            "je nach Gerätetyp)."
        )
    return (
        f"Du hilfst bei der Inbetriebnahme eines Modbus-Geräts. Gerät: {device_desc or 'unbekannt'}.\n\n"
        f"{task}\n\n"
        "Suche gezielt nach der offiziellen Modbus-Registerkarte/Dokumentation des Herstellers "
        "(PDF-Handbücher, technische Datenblätter). Falls du das genaue Gerät nicht eindeutig "
        "identifizieren kannst, sag das ehrlich (device_identified=false) und leite die Vorschläge "
        "stattdessen aus typischen Konventionen für diese Geräteklasse ab, markiere sie dann als "
        "Konfidenz 'niedrig'.\n\n"
        "Wichtige Hinweise für deine Antwort:\n"
        "- Modbus-Dokumentation nennt Adressen oft als 4xxxx (Holding, 1-basiert) oder 3xxxx "
        "(Input, 1-basiert). Wenn du eine solche Adresse findest, gib im Feld 'address' die "
        "wahrscheinliche 0-basierte Registeradresse an und erkläre die Umrechnung in 'address_notes'.\n"
        "- 'function' ist der Modbus-Funktionscode (1=Coils, 2=Discrete Inputs, 3=Holding "
        "Registers, 4=Input Registers) - falls unklar, lass das Feld weg und erläutere in "
        "'function_guess_note'.\n"
        "- 'data_type' muss einer von: " + ", ".join(DATA_TYPES) + " sein.\n"
        "- 'order' ist die Byte-/Wort-Reihenfolge, z. B. 'AB'/'BA' für 16-Bit oder "
        "'ABCD'/'BADC'/'CDAB'/'DCBA' für 32-Bit-Werte - wähle die für den Hersteller übliche Reihenfolge.\n"
        "- 'quantity_kind' beschreibt die physikalische Grösse (" + ", ".join(QUANTITY_KINDS) + ").\n"
        "- 'scale' ist der Faktor, mit dem der Rohwert multipliziert werden muss, um den realen Wert "
        "zu erhalten (z. B. 0.1 wenn das Register in Zehntelvolt steht).\n"
        "- Gib in 'source_url' die konkrete Quelle an (Handbuch-URL), wenn du eine gefunden hast.\n"
        "- Antworte auf Deutsch in den Textfeldern.\n"
        f"- Maximal {MAX_SUGGESTIONS} Vorschläge."
    )


def validate_suggestions_payload(raw: Any) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get("points"), list):
        raise InspectorError("Antwort der KI konnte nicht ausgewertet werden.", 502)

    points = []
    for item in raw["points"][:MAX_SUGGESTIONS]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        data_type = item.get("data_type")
        order = item.get("order")
        confidence = item.get("confidence")
        if not name or data_type not in TYPE_COUNTS:
            continue
        width = TYPE_COUNTS[data_type] * 2
        valid_orders = ORDERS.get(width, ())
        if order not in valid_orders:
            order = valid_orders[0] if valid_orders else ""
        quantity_kind = item.get("quantity_kind")
        if quantity_kind not in QUANTITY_KINDS:
            quantity_kind = "other"
        if confidence not in CONFIDENCE_LEVELS:
            confidence = "niedrig"
        function = item.get("function")
        if not isinstance(function, int) or function not in (1, 2, 3, 4):
            function = None
        address = item.get("address")
        if not isinstance(address, int) or address < 0:
            address = None
        scale = item.get("scale")
        if not isinstance(scale, (int, float)):
            scale = None
        points.append(
            {
                "name": name[:160],
                "quantity_kind": quantity_kind,
                "function": function,
                "function_guess_note": str(item.get("function_guess_note") or "").strip()[:500],
                "address": address,
                "address_notes": str(item.get("address_notes") or "").strip()[:500],
                "data_type": data_type,
                "order": order,
                "scale": scale,
                "unit": str(item.get("unit") or "").strip()[:40],
                "confidence": confidence,
                "source_url": str(item.get("source_url") or "").strip()[:500],
                "source_note": str(item.get("source_note") or "").strip()[:500],
                "caveats": str(item.get("caveats") or "").strip()[:500],
            }
        )

    return {
        "device_identified": bool(raw.get("device_identified")),
        "general_notes": str(raw.get("general_notes") or "").strip()[:2000],
        "warnings": [str(w).strip()[:500] for w in raw.get("warnings") or [] if str(w).strip()][:20],
        "points": points,
    }
