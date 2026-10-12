"""evcc-Zählervorlagen (MIT) in Einträge für das Geräte-Nachschlagewerk umwandeln.

Quelle: https://github.com/evcc-io/evcc/tree/master/templates/definition/meter (MIT-Lizenz, © evcc.io).
Die Vorlagen sind Go-Templates. Ausgewertet werden die üblichen Bedingungen (`if eq .usage "grid"` …) je
Verwendung; Vorlagen mit nicht auswertbaren Konstrukten werden ausgelassen. Übernommen werden nur
Lese-Register (holding/input) mit eindeutigem Datentyp.

Aufruf (benötigt PyYAML, nur zum Erzeugen):
  python tools/import_evcc_meters.py <evcc>/templates/definition/meter device-catalog-entries/evcc-meters.hbdevicecatalog.json
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

SOURCE_BASE = "https://github.com/evcc-io/evcc/blob/master/templates/definition/meter/"
TAG = re.compile(r"\{\{-?\s*(.*?)\s*-?\}\}")
# evcc-decode → (Datentyp, Reihenfolge); Endung s = Word-Tausch, nan = «kein Wert»-Kennung (für uns gleicher Typ)
DECODE = {
    "int16": ("int16", "AB"), "uint16": ("uint16", "AB"), "int32": ("int32", "ABCD"), "uint32": ("uint32", "ABCD"),
    "float32": ("float32", "ABCD"), "int64": ("int64", "ABCDEFGH"), "uint64": ("uint64", "ABCDEFGH"),
    "float64": ("float64", "ABCDEFGH"), "int32s": ("int32", "CDAB"), "uint32s": ("uint32", "CDAB"),
    "float32s": ("float32", "CDAB"), "uint64s": ("uint64", "GHEFCDAB"),
}
REGISTER_TYPES = {"holding": 3, "input": 4}
NAMES = {  # evcc-Schlüssel → (Bezeichnung, Messgrösse, Einheit)
    "power": ("Wirkleistung gesamt", "power", "W"),
    "energy": ("Energie Bezug (Zählerstand)", "energy", "kWh"),
    "returnenergy": ("Energie Einspeisung (Zählerstand)", "energy", "kWh"),
    "soc": ("Ladezustand", "percent", "%"),
    "capacity": ("Kapazität", "energy", "kWh"),
    "maxacpower": ("Max. AC-Leistung", "power", "W"),
    "currents": ("Strom L{n}", "current", "A"),
    "voltages": ("Spannung L{n}", "voltage", "V"),
    "powers": ("Wirkleistung L{n}", "power", "W"),
}
USAGE_LABELS = {"grid": "Netz", "pv": "PV", "battery": "Batterie", "charge": "Laden", "aux": "Verbraucher"}


class Unsupported(Exception):
    pass


PARAMS: dict[str, str] = {}  # Standardwerte der Vorlagen-Parameter (je Vorlage gesetzt)


def _param(name: str) -> str:
    return PARAMS.get(name, "")


def _condition(expr: str, usage: str | None) -> bool:
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1].strip()
    if expr.startswith("or "):
        return any(_condition(part, usage) for part in re.findall(r"\(([^()]*)\)", expr))
    if expr.startswith("and "):
        return all(_condition(part, usage) for part in re.findall(r"\(([^()]*)\)", expr))
    if expr.startswith("not "):
        return not _condition(expr[4:], usage)
    match = re.fullmatch(r'(eq|ne) \.usage "([^"]+)"', expr)
    if match:
        same = usage == match.group(2)
        return same if match.group(1) == "eq" else not same
    match = re.fullmatch(r'(eq|ne) \.([A-Za-z0-9_]+) "([^"]*)"', expr)
    if match:  # andere Parameter: mit ihrem Standardwert vergleichen
        same = _param(match.group(2)) == match.group(3)
        return same if match.group(1) == "eq" else not same
    match = re.fullmatch(r"\.([A-Za-z0-9_]+)", expr)
    if match:
        return _param(match.group(1)) not in ("", "false", "0")  # optionale Parameter: Standardwert
    raise Unsupported(expr)


def render(template: str, usage: str | None) -> str:
    out, stack, pos = [], [], 0  # stack: [aktiv, schon_ein_zweig_wahr]
    def active() -> bool:
        return all(level[0] for level in stack)
    for match in TAG.finditer(template):
        if active():
            out.append(template[pos:match.start()])
        pos = match.end()
        tag = match.group(1)
        if tag.startswith("include ") or tag.startswith("/*"):
            continue
        if tag.startswith("if "):
            value = _condition(tag[3:], usage)
            stack.append([value, value])
        elif tag.startswith("else if "):
            level = stack[-1]
            value = not level[1] and _condition(tag[8:], usage)
            level[0], level[1] = value, level[1] or value
        elif tag == "else":
            level = stack[-1]
            level[0], level[1] = not level[1], True
        elif tag == "end":
            stack.pop()
        elif tag.startswith("range ") or tag.startswith("define ") or tag.startswith("template "):
            raise Unsupported(tag)  # Schleifen: Vorlage für diese Verwendung auslassen
        elif re.fullmatch(r"\.[A-Za-z0-9_]+", tag):
            if active():
                out.append(_param(tag[1:]))  # Platzhalter durch Standardwert ersetzen
        else:
            if active():
                out.append("0")  # Rechenfunktionen (mul, divf …) betreffen nur Einstellwerte, nicht Register

    if active():
        out.append(template[pos:])
    if stack:
        raise Unsupported("unvollständige if/end")
    return "".join(out)


def _leaf_points(key: str, node, index: int | None = None, part: int | None = None):
    if isinstance(node, list):
        for i, item in enumerate(node):
            yield from _leaf_points(key, item, i, part)
        return
    if not isinstance(node, dict):
        return
    if node.get("source") == "modbus":
        register = node.get("register") or {}
        yield key, index, register, node.get("scale", 1), part
        return
    for child_key in ("add", "mul"):
        if isinstance(node.get(child_key), list):
            for number, item in enumerate(node[child_key], start=1):
                yield from _leaf_points(key, item, index, number)  # evcc rechnet aus mehreren Registern


def points_for(rendered: str) -> list[dict]:
    data = yaml.safe_load(rendered) or {}
    points = []
    for key, value in data.items():
        if key not in NAMES:
            continue
        for _, index, register, scale, part in _leaf_points(key, value):
            decode = str(register.get("decode", "")).replace("nan", "")
            function = REGISTER_TYPES.get(str(register.get("type", "")).lower())
            address = register.get("address")
            if decode not in DECODE or function is None or not isinstance(address, int):
                continue
            data_type, order = DECODE[decode]
            label, kind, unit = NAMES[key]
            name = label.format(n=(index or 0) + 1) if "{n}" in label else label
            if part:
                name += f" – Teil {part} (evcc addiert)"
            points.append({"name": name, "quantity_kind": kind, "function": function, "address": address,
                           "data_type": data_type, "order": order, "scale": float(scale) if scale not in (None, "") else 1.0,
                           "unit": unit, "confidence": "mittel"})
    return points


def convert(path: Path) -> list[dict]:
    template = yaml.safe_load(path.read_text(encoding="utf-8"))
    body = template.get("render") or ""
    if "source: modbus" not in body:
        return []
    PARAMS.clear()
    for param in template.get("params", []):
        if param.get("name") and param.get("name") != "usage":
            default = param.get("default", (param.get("choice") or [""])[0])
            PARAMS[param["name"]] = str(default).lower() if isinstance(default, bool) else str(default)
    usages = next((param.get("choice") for param in template.get("params", []) if param.get("name") == "usage"), None) or [None]
    merged: dict[tuple, dict] = {}
    for usage in usages:
        try:
            points = points_for(render(body, usage))
        except (Unsupported, yaml.YAMLError):
            continue
        for point in points:
            key = (point["function"], point["address"], point["data_type"], point["order"], point["scale"], point["name"])
            entry = merged.setdefault(key, {**point, "_usages": []})
            if usage:
                entry["_usages"].append(USAGE_LABELS.get(usage, usage))
    if not merged:
        return []
    all_usages = [USAGE_LABELS.get(u, u) for u in usages if u]
    points = []
    for point in merged.values():
        used = point.pop("_usages")
        if used and len(set(used)) < len(set(all_usages)):
            point["name"] = f"{point['name']} ({'/'.join(dict.fromkeys(used))})"
        points.append(point)
    points.sort(key=lambda p: (p["function"], p["address"], p["name"]))
    if "Batterie" in all_usages:
        device_type = "batteriespeicher"
    elif all_usages and set(all_usages) <= {"PV"}:
        device_type = "wechselrichter"
    elif "PV" in all_usages and "Netz" not in all_usages:
        device_type = "wechselrichter"
    else:
        device_type = "energiezaehler"
    entries = []
    products = template.get("products") or [{}]
    names = []
    for product in products:
        description = product.get("description") or {}
        model = description.get("generic") or description.get("de") or description.get("en") or template.get("template")
        names.append((str(product.get("brand") or "Unbekannt").strip(), str(model).strip()))
    brand, model = names[0]
    if brand == "Unbekannt":
        return []  # generische Vorlagen ohne Hersteller (z. B. SunSpec allgemein) nicht übernehmen
    aliases = ", ".join(f"{b} {m}" for b, m in names[1:])
    entries.append({
        "schema": "hbtec-device-catalog-entry", "schema_version": 1,
        "manufacturer": brand, "model": model, "device_type": device_type, "aliases": aliases,
        "notes": ("Aus der evcc-Vorlage «%s» übernommen (Verwendungen: %s). Werte in W, kWh, A, V bzw. %%; Faktoren wie in evcc. "
                  "Unit-ID und Verbindung je Anlage prüfen; Angaben vor Verwendung mit dem Register-Finder verifizieren.")
                 % (template.get("template"), ", ".join(all_usages) or "–"),
        "source_url": SOURCE_BASE + path.name,
        "source_note": "evcc Gerätevorlage (MIT-Lizenz, © evcc.io)",
        "verified": False,
        "points": points,
    })
    return entries


def main(source: str, target: str) -> None:
    entries, skipped = [], []
    for path in sorted(Path(source).glob("*.yaml")):
        try:
            converted = convert(path)
        except Exception as error:  # noqa: BLE001 – einzelne Vorlage überspringen
            skipped.append(f"{path.name}: {error}")
            continue
        if converted:
            entries.extend(converted)
    payload = {"schema": "hbtec-device-catalog", "schema_version": 1,
               "source": "evcc-io/evcc templates/definition/meter (MIT)", "entries": entries}
    Path(target).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(entries)} Einträge mit {sum(len(e['points']) for e in entries)} Datenpunkten → {target}")
    if skipped:
        print("Übersprungen:", *skipped, sep="\n  ")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
