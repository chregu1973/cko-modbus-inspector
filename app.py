from __future__ import annotations

import os
import socket
import sqlite3
import sys
import time
import webbrowser
from pathlib import Path
from threading import Timer

from flask import Flask, jsonify, render_template, request

from ai_lookup import lookup_device_points, lookup_quantity
from ai_settings import AiSettingsStore
from device_catalog import DEVICE_TYPE_LABELS, DeviceCatalogStore
from gemini_lookup import lookup_device_points as gemini_lookup_device_points
from gemini_lookup import lookup_quantity as gemini_lookup_quantity
from modbus_core import (
    InspectorError,
    connect_test,
    list_interfaces,
    match_register_values,
    poll_points,
    read_values,
    scan_network,
    scan_registers,
    scan_unit_ids,
)
from profile_store import ProfileStore


APP_VERSION = "0.2.1"
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


@app.get("/api/health")
def health():
    return jsonify(
        {
            "ok": True,
            "service": "CKO Modbus Inspector",
            "version": APP_VERSION,
            "read_only": True,
        }
    )


@app.get("/api/interfaces")
def interfaces():
    return jsonify({"ok": True, "interfaces": list_interfaces()})


@app.post("/api/connect")
def connect():
    payload = request.get_json(force=True, silent=False) or {}
    return jsonify(connect_test(payload))


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
