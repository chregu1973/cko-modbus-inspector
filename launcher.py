"""Windows-Start des CKO Modbus Inspector ohne Konsolenfenster.

Startet den lokalen Server und öffnet den Browser. Läuft bereits eine Instanz,
wird nur der Browser geöffnet. Beendet wird über «Tool beenden» in der Oberfläche.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path
from threading import Timer

DEFAULT_PORT = 48722


def log_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hbTec" / "ModbusInspector"
    base.mkdir(parents=True, exist_ok=True)
    return base


def redirect_output() -> None:
    # Ohne Konsole sind stdout/stderr None; Meldungen landen in einer Logdatei
    if sys.stdout is None or sys.stderr is None:
        stream = open(log_dir() / "inspector.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


def show_error(message: str) -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, "CKO Modbus Inspector", 0x10)
    else:
        print(message, file=sys.stderr)


def port_free(port: int) -> bool:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        probe.close()


def running_inspector(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as response:
            return json.load(response).get("service") == "CKO Modbus Inspector"
    except (OSError, ValueError):
        return False


def main() -> int:
    redirect_output()
    port = int(os.getenv("HBMODBUS_PORT", str(DEFAULT_PORT)))
    url = f"http://127.0.0.1:{port}"
    if not port_free(port):
        if running_inspector(port):
            webbrowser.open_new(url)
            return 0
        show_error(f"Port {port} ist von einem anderen Programm belegt.\nDer CKO Modbus Inspector kann nicht starten.")
        return 2

    from app import app

    Timer(1.0, webbrowser.open_new, args=(url,)).start()
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001 – ohne Konsole sonst unsichtbar
        show_error(f"Der CKO Modbus Inspector konnte nicht gestartet werden:\n{error}")
        raise
