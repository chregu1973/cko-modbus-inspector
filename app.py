from __future__ import annotations

import json
import os
import socket
import sqlite3
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, render_template, request

from ai_lookup import lookup_device_points, lookup_quantity
from ai_settings import AiSettingsStore
from device_catalog import DEVICE_TYPE_LABELS, DeviceCatalogStore
from gemini_lookup import lookup_device_points as gemini_lookup_device_points
from gemini_lookup import lookup_quantity as gemini_lookup_quantity
from ha_export import build_yaml as build_ha_yaml
from loxone_import import convert as convert_loxone
from meter_list import build_csv as build_meter_csv
from meter_list import build_rows as build_meter_rows
from modbus_core import (
    InspectorError,
    connect_test,
    connection_status,
    encode_value,
    list_interfaces,
    list_serial_ports,
    match_register_values,
    poll_points,
    read_values,
    rtu_probe,
    scan_network,
    scan_registers,
    scan_unit_ids,
    set_write_mode,
    sunspec_scan,
    write_mode_status,
    write_value,
)
from profile_store import ProfileStore


APP_VERSION = "0.5.0"
DEFAULT_PORT = 48722
# Mitgelieferte Geräteeinträge; im Windows-Setup liegen sie neben dem Programmcode
BUNDLED_CATALOG_DIR = Path(__file__).resolve().parent / "device-catalog-entries"

_profile_store = None
_ai_settings_store = None
_device_catalog_store = None

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["JSON_SORT_KEYS"] = False


def profile_store():
    global _profile_store
    if _profile_store is None:
        _profile_store = ProfileStore()
    return _profile_store


def ai_settings_store():
    global _ai_settings_store
    if _ai_settings_store is None:
        _ai_settings_store = AiSettingsStore()
    return _ai_settings_store


def device_catalog_store():
    global _device_catalog_store
    if _device_catalog_store is None:
        _device_catalog_store = DeviceCatalogStore()
        try:
            _device_catalog_store.seed_from_directory(BUNDLED_CATALOG_DIR)
        except sqlite3.Error:
            pass  # Nachschlagewerk bleibt nutzbar, die Startdateien lassen sich auch von Hand importieren
    return _device_catalog_store


@app.after_request
def add_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.errorhandler(InspectorError)
def handle_inspector_error(error):
    return jsonify({"ok": False, "error": str(error)}), error.status_code


@app.errorhandler(400)
def handle_bad_request(error):
    return jsonify({"ok": False, "error": "Ungültige Anfrage."}), 400


@app.errorhandler(500)
def handle_server_error(error):
    return jsonify({"ok": False, "error": "Interner Fehler im lokalen Connector."}), 500


@app.get("/")
def index():
    return render_template("index.html", app_version=APP_VERSION)


# Update-Prüfung: fragt nur die öffentliche Versionsliste der CKO Toolbox ab, keine Projekt- oder Anlagendaten
TOOLS_JSON_URL = "https://toolbox.ckoeppen.ch/data/tools.json"
DOWNLOAD_PAGE = "https://toolbox.ckoeppen.ch/tools/modbus-inspector/#download"
TOOL_ID = "modbus-inspector"


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for part in str(value).split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _fetch_latest_version(timeout: float = 4.0) -> str | None:
    request = urllib.request.Request(TOOLS_JSON_URL, headers={"User-Agent": f"CKO-Modbus-Inspector/{APP_VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        tools = json.loads(response.read(512 * 1024).decode("utf-8"))
    entry = next((tool for tool in tools if isinstance(tool, dict) and tool.get("id") == TOOL_ID), None)
    return str(entry["version"]) if entry and entry.get("version") else None


@app.get("/api/update-check")
def update_check():
    try:
        latest = _fetch_latest_version()
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify({"ok": True, "checked": False, "current": APP_VERSION, "latest": None, "update_available": False})
    available = bool(latest) and _version_tuple(latest) > _version_tuple(APP_VERSION)
    return jsonify({"ok": True, "checked": latest is not None, "current": APP_VERSION, "latest": latest,
                    "update_available": available, "download_url": DOWNLOAD_PAGE})


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "CKO Modbus Inspector",
            "version": APP_VERSION,
            "read_only": not write_mode_status()["enabled"],
        }
    )


@app.get("/api/interfaces")
def interfaces():
    return jsonify({"ok": True, "interfaces": list_interfaces()})


@app.post("/api/connect")
def connect():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(connect_test(payload))


@app.get("/api/serial-ports")
def serial_ports():
    return jsonify(list_serial_ports())


@app.post("/api/rtu-probe")
def rtu_probe_route():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(rtu_probe(payload))


@app.post("/api/network-scan")
def network_scan():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(scan_network(payload))


@app.post("/api/unit-scan")
def unit_scan():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(scan_unit_ids(payload))


@app.post("/api/read")
def read():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(read_values(payload))


@app.post("/api/register-scan")
def register_scan():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(scan_registers(payload))


@app.post("/api/match-values")
def match_values():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(match_register_values(payload))


@app.post("/api/poll")
def poll():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(poll_points(payload))


@app.get("/api/connections")
def connections():
    return jsonify(connection_status())


@app.get("/api/write-mode")
def write_mode_get():
    return jsonify(write_mode_status())


@app.post("/api/write-mode")
def write_mode_set():
    payload = request.get_json(force=True, silent=True) or {}
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Schreiben kann nur lokal freigegeben werden."}), 403
    return jsonify(set_write_mode(bool(payload.get("enabled"))))


@app.post("/api/sunspec-scan")
def sunspec_scan_route():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(sunspec_scan(payload))


@app.post("/api/encode-preview")
def encode_preview():
    """Zeigt, welche Registerwerte ein Schreibvorgang senden würde – ohne zu senden."""
    payload = request.get_json(force=True, silent=False) or {}
    function = int(payload.get("function", 3))
    if function == 1:
        on = str(payload.get("value")).strip().lower() in ("1", "true", "ein", "on", "an")
        return jsonify({"ok": True, "function": "FC05", "registers": [], "hex": "EIN (0xFF00)" if on else "AUS (0x0000)"})
    if function in (2, 4):
        raise InspectorError("Discrete Inputs (FC02) und Input Register (FC04) sind nur lesbar.", 400)
    data_type = str(payload.get("data_type", "uint16")).lower()
    length = int(payload.get("length", 1) or 1) if data_type == "string" else None
    registers = encode_value(payload.get("value"), data_type, payload.get("order"),
                             float(payload.get("scale", 1) or 1), float(payload.get("offset", 0) or 0), length)
    code = "FC16" if len(registers) > 1 or payload.get("prefer_fc16") else "FC06"
    return jsonify({"ok": True, "function": code, "registers": registers,
                    "hex": " ".join(f"0x{value:04X}" for value in registers)})


@app.post("/api/write")
def write():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Schreiben ist nur lokal erlaubt."}), 403
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(write_value(payload))


@app.post("/api/export/home-assistant")
def export_home_assistant():
    payload = request.get_json(force=True, silent=False) or {}
    try:
        text = build_ha_yaml(payload.get("points") or [], payload.get("connection") or {},
                             str(payload.get("name") or ""), int(payload.get("scan_interval") or 15))
    except (ValueError, TypeError) as error:
        raise InspectorError(str(error), 400)
    return jsonify({"ok": True, "yaml": text})


@app.post("/api/export/meter-list")
def export_meter_list():
    payload = request.get_json(force=True, silent=False) or {}
    try:
        rows = build_meter_rows(payload.get("points") or [], payload.get("connection") or {}, payload.get("values") or {})
    except (ValueError, TypeError) as error:
        raise InspectorError(str(error), 400)
    return jsonify({"ok": True, "rows": rows, "csv": build_meter_csv(rows),
                    "warnings": sum(1 for row in rows if row["hints"])})


@app.get("/api/profile-library")
def profile_library_list():
    try:
        profiles = profile_store().list(request.args.get("q", ""))
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(f"Profilbibliothek konnte nicht gelesen werden: {error}", 500)
    return jsonify({"ok": True, "profiles": profiles})


@app.post("/api/profile-library")
def profile_library_save():
    body = request.get_json(force=True, silent=False) or {}
    try:
        metadata = profile_store().save(body.get("profile"), body.get("id"))
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(str(error))
    return jsonify({"ok": True, "profile": metadata})


@app.get("/api/profile-library/<profile_id>")
def profile_library_get(profile_id):
    try:
        profile = profile_store().get(profile_id)
    except KeyError as error:
        raise InspectorError(str(error.args[0]), 404)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(f"Geräteprofil konnte nicht gelesen werden: {error}", 500)
    return jsonify({"ok": True, **profile})


@app.delete("/api/profile-library/<profile_id>")
def profile_library_delete(profile_id):
    try:
        deleted = profile_store().delete(profile_id)
    except (OSError, sqlite3.Error) as error:
        raise InspectorError(f"Geräteprofil konnte nicht gelöscht werden: {error}", 500)
    if not deleted:
        raise InspectorError("Geräteprofil wurde nicht gefunden.", 404)
    return jsonify({"ok": True})


@app.get("/api/profile-library-backup")
def profile_library_backup():
    try:
        backup = profile_store().export_backup()
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(f"Profilbibliothek konnte nicht exportiert werden: {error}", 500)
    return jsonify({"ok": True, "backup": backup})


@app.post("/api/profile-library-backup")
def profile_library_restore():
    body = request.get_json(force=True, silent=False) or {}
    try:
        result = profile_store().import_backup(body.get("backup"))
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(str(error))
    return jsonify({"ok": True, **result})


PROVIDER_LABELS = {"anthropic": "Anthropic", "gemini": "Google Gemini"}


def _ai_settings_payload(store: AiSettingsStore) -> dict:
    return {
        "provider": store.get_provider(),
        "providers": {
            "anthropic": {
                "has_api_key": store.has_api_key(),
                "api_key_masked": store.get_api_key_masked(),
            },
            "gemini": {
                "has_api_key": store.has_gemini_api_key(),
                "api_key_masked": store.get_gemini_api_key_masked(),
            },
        },
    }


@app.get("/api/ai-settings")
def ai_settings_get():
    try:
        return jsonify({"ok": True, **_ai_settings_payload(ai_settings_store())})
    except (OSError, sqlite3.Error) as error:
        raise InspectorError(f"KI-Einstellungen konnten nicht gelesen werden: {error}", 500)


@app.post("/api/ai-settings")
def ai_settings_post():
    body = request.get_json(force=True, silent=False) or {}
    try:
        store = ai_settings_store()
        if "anthropic_api_key" in body:
            store.set_api_key(body.get("anthropic_api_key"))
        if "gemini_api_key" in body:
            store.set_gemini_api_key(body.get("gemini_api_key"))
        if body.get("provider"):
            store.set_provider(body.get("provider"))
        return jsonify({"ok": True, **_ai_settings_payload(store)})
    except ValueError as error:
        raise InspectorError(str(error), 400)
    except (OSError, sqlite3.Error) as error:
        raise InspectorError(f"KI-Einstellungen konnten nicht gespeichert werden: {error}", 500)


@app.post("/api/ai/lookup")
def ai_lookup():
    body = request.get_json(force=True, silent=False) or {}
    manufacturer = str(body.get("manufacturer") or "").strip()
    model = str(body.get("model") or "").strip()
    firmware = str(body.get("firmware") or "").strip()
    quantity = str(body.get("quantity") or "").strip()

    if not manufacturer and not model:
        raise InspectorError("Bitte zuerst Hersteller oder Modell angeben.", 400)

    store = ai_settings_store()
    provider = store.get_provider()
    if provider == "gemini":
        api_key = store.get_gemini_api_key()
        points_fn, quantity_fn = gemini_lookup_device_points, gemini_lookup_quantity
    else:
        api_key = store.get_api_key()
        points_fn, quantity_fn = lookup_device_points, lookup_quantity

    if not api_key:
        raise InspectorError(
            f"Kein {PROVIDER_LABELS[provider]}-API-Schlüssel hinterlegt. "
            "Bitte zuerst in den KI-Einstellungen ergänzen.",
            400,
        )

    if quantity:
        result = quantity_fn(manufacturer, model, firmware, quantity, api_key)
    else:
        result = points_fn(manufacturer, model, firmware, api_key)

    return jsonify({"ok": True, "provider": provider, **result})


@app.get("/api/device-catalog")
def device_catalog_list():
    try:
        store = device_catalog_store()
        entries = store.list(request.args.get("q", ""), request.args.get("type", ""), status=request.args.get("status", ""))
        counts = store.counts()
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(f"Katalog konnte nicht gelesen werden: {error}", 500)
    return jsonify({"ok": True, "entries": entries, "counts": counts})


@app.get("/api/device-catalog-types")
def device_catalog_types():
    return jsonify(
        {"ok": True, "types": [{"value": value, "label": label} for value, label in DEVICE_TYPE_LABELS.items()]}
    )


@app.get("/api/device-catalog/<entry_id>")
def device_catalog_get(entry_id):
    try:
        entry = device_catalog_store().get(entry_id)
    except KeyError as error:
        raise InspectorError(str(error.args[0]), 404)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(f"Katalogeintrag konnte nicht gelesen werden: {error}", 500)
    return jsonify({"ok": True, **entry})


@app.delete("/api/device-catalog/<entry_id>")
def device_catalog_delete(entry_id):
    try:
        deleted = device_catalog_store().delete(entry_id)
    except (OSError, sqlite3.Error) as error:
        raise InspectorError(f"Katalogeintrag konnte nicht gelöscht werden: {error}", 500)
    if not deleted:
        raise InspectorError("Katalogeintrag wurde nicht gefunden.", 404)
    return jsonify({"ok": True})


@app.post("/api/device-catalog-import")
def device_catalog_import():
    body = request.get_json(force=True, silent=False) or {}
    try:
        result = device_catalog_store().import_payload(body.get("data"))
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(str(error), 400)
    return jsonify({"ok": True, **result})


@app.post("/api/device-catalog-import-loxone")
def device_catalog_import_loxone():
    body = request.get_json(force=True, silent=False) or {}
    xml_text = str(body.get("xml") or "")
    if len(xml_text) > 2_000_000:
        raise InspectorError("Die Loxone-Vorlage ist grösser als 2 MB.", 400)
    try:
        entry = convert_loxone(xml_text, str(body.get("filename") or ""))
        result = device_catalog_store().import_payload(entry)
    except (OSError, sqlite3.Error, ValueError) as error:
        raise InspectorError(str(error), 400)
    return jsonify({"ok": True, **result, "manufacturer": entry["manufacturer"], "model": entry["model"],
                    "points": len(entry["points"])})


def terminate_process():
    # The app is a local desktop helper. os._exit reliably stops all Flask
    # worker threads on Windows when launched by start-windows.bat.
    time.sleep(0.25)
    os._exit(0)


@app.post("/api/shutdown")
def shutdown():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"ok": False, "error": "Beenden ist nur lokal erlaubt."}), 403
    Timer(0.05, terminate_process).start()
    return jsonify({"ok": True, "message": "Der lokale Server wird beendet."})


def open_browser(port: int):
    webbrowser.open_new(f"http://127.0.0.1:{port}")


def ensure_port_available(port: int):
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        print()
        print(f"Port {port} ist bereits belegt.")
        print("Wahrscheinlich läuft noch eine ältere Version des CKO Modbus Inspector.")
        print("Bitte das alte Konsolenfenster mit Strg+C beenden und erneut starten.")
        sys.exit(2)
    finally:
        probe.close()


if __name__ == "__main__":
    port = int(os.getenv("HBMODBUS_PORT", str(DEFAULT_PORT)))
    ensure_port_available(port)
    if os.getenv("HBMODBUS_NO_BROWSER") != "1":
        Timer(1.0, open_browser, args=(port,)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
