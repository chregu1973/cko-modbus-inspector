from __future__ import annotations

import inspect
import ipaddress
import math
import os
import re
import socket
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - fallback for minimal environments
    psutil = None

try:
    from pymodbus import FramerType
    from pymodbus.client import ModbusTcpClient
    from pymodbus.exceptions import ModbusException
except ImportError:  # pragma: no cover - reported clearly at runtime
    ModbusTcpClient = None
    FramerType = None

    class ModbusException(Exception):
        pass


class InspectorError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


FUNCTIONS = {
    1: ("Coils", "read_coils"),
    2: ("Discrete Inputs", "read_discrete_inputs"),
    3: ("Holding Registers", "read_holding_registers"),
    4: ("Input Registers", "read_input_registers"),
}

TYPE_COUNTS = {
    "bool": 1,
    "uint16": 1,
    "int16": 1,
    "uint32": 2,
    "int32": 2,
    "float32": 2,
    "uint64": 4,
    "int64": 4,
    "float64": 4,
}

MATCH_TYPE_MODES = {
    "auto": ("uint16", "int16", "uint32", "int32", "float32"),
    "16": ("uint16", "int16"),
    "32": ("uint32", "int32", "float32"),
    "64": ("uint64", "int64", "float64"),
    "all": ("uint16", "int16", "uint32", "int32", "float32", "uint64", "int64", "float64"),
}

MATCH_LABELS = {
    "uint16": "UInt16",
    "int16": "Int16",
    "uint32": "UInt32",
    "int32": "Int32",
    "float32": "Float32",
    "uint64": "UInt64",
    "int64": "Int64",
    "float64": "Float64",
}

MATCH_FACTORS = (
    1.0,
    0.1,
    0.01,
    0.001,
    0.0001,
    0.00001,
    0.000001,
    10.0,
    100.0,
    1000.0,
)

VISU_TYPES = {
    "uint16": "UINT16",
    "int16": "SINT16",
    "uint32": "UINT32",
    "int32": "SINT32",
    "float32": "FLOAT32",
    "uint64": "UINT64",
    "int64": "SINT64",
    "float64": "FLOAT64",
}

# A close number is not automatically the correct register. These profiles
# describe common Modbus encodings and keep a coincidental byte-swapped 16-bit
# value from outranking a plausible 32-bit measurement.
QUANTITY_TYPE_SCORES = {
    "free": {
        "uint16": 82, "int16": 82, "uint32": 94, "int32": 94,
        "float32": 92, "uint64": 80, "int64": 80, "float64": 78,
    },
    "energy": {
        "uint16": 68, "int16": 55, "uint32": 100, "int32": 92,
        "float32": 82, "uint64": 94, "int64": 84, "float64": 78,
    },
    "power": {
        "uint16": 42, "int16": 62, "uint32": 52, "int32": 100,
        "float32": 92, "uint64": 64, "int64": 82, "float64": 76,
    },
    "voltage": {
        "uint16": 86, "int16": 70, "uint32": 84, "int32": 76,
        "float32": 100, "uint64": 62, "int64": 58, "float64": 82,
    },
    "current": {
        "uint16": 78, "int16": 82, "uint32": 82, "int32": 88,
        "float32": 100, "uint64": 60, "int64": 64, "float64": 82,
    },
    "frequency": {
        "uint16": 88, "int16": 72, "uint32": 82, "int32": 74,
        "float32": 100, "uint64": 55, "int64": 52, "float64": 78,
    },
    "temperature": {
        "uint16": 62, "int16": 92, "uint32": 70, "int32": 88,
        "float32": 100, "uint64": 50, "int64": 62, "float64": 78,
    },
    "percent": {
        "uint16": 94, "int16": 84, "uint32": 76, "int32": 72,
        "float32": 88, "uint64": 48, "int64": 48, "float64": 68,
    },
}

ORDERS = {
    2: ("AB", "BA"),
    4: ("ABCD", "BADC", "CDAB", "DCBA"),
    8: ("ABCDEFGH", "BADCFEHG", "GHEFCDAB", "HGFEDCBA"),
}


@dataclass(frozen=True)
class Target:
    host: str
    port: int
    timeout: float
    transport: str


def _int(value: Any, name: str, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise InspectorError(f"{name} muss eine ganze Zahl sein.")
    if not minimum <= parsed <= maximum:
        raise InspectorError(f"{name} muss zwischen {minimum} und {maximum} liegen.")
    return parsed


def _float(value: Any, name: str, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        raise InspectorError(f"{name} muss eine Zahl sein.")
    if not minimum <= parsed <= maximum:
        raise InspectorError(f"{name} muss zwischen {minimum} und {maximum} liegen.")
    return parsed


def _resolve_private_host(host: Any) -> str:
    host = str(host or "").strip()
    if not host:
        raise InspectorError("IP-Adresse oder Hostname fehlt.")
    try:
        address = ipaddress.ip_address(socket.gethostbyname(host))
    except (ValueError, socket.gaierror):
        raise InspectorError("Host konnte nicht aufgelöst werden.")

    public_allowed = os.getenv("HBMODBUS_ALLOW_PUBLIC") == "1"
    if not public_allowed and not (
        address.is_private or address.is_loopback or address.is_link_local
    ):
        raise InspectorError(
            "Aus Sicherheitsgründen sind nur lokale oder private Zielnetze erlaubt."
        )
    return str(address)


def _target(payload: dict[str, Any]) -> Target:
    connection = payload.get("connection", payload)
    host = _resolve_private_host(connection.get("host"))
    port = _int(connection.get("port", 502), "Port", 1, 65535)
    timeout_ms = _int(connection.get("timeout_ms", 800), "Timeout", 50, 10000)
    transport = str(connection.get("transport", "tcp")).strip().lower()
    if transport not in ("tcp", "rtu_tcp"):
        raise InspectorError("Unbekannte Übertragungsart. Erlaubt sind Modbus TCP und RTU über TCP.")
    return Target(host, port, timeout_ms / 1000, transport)


def _require_modbus():
    if ModbusTcpClient is None:
        raise InspectorError(
            "Die Python-Abhängigkeit 'pymodbus' fehlt. Bitte start-windows.bat erneut ausführen.",
            503,
        )


def _client(target: Target):
    _require_modbus()
    options = {"port": target.port, "timeout": target.timeout}
    if target.transport == "rtu_tcp":
        options["framer"] = FramerType.RTU
    try:
        signature = inspect.signature(ModbusTcpClient)
        if "retries" in signature.parameters:
            options["retries"] = 0
    except (TypeError, ValueError):
        pass
    return ModbusTcpClient(target.host, **options)


def _unit_kw(method, unit_id: int) -> dict[str, int]:
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "device_id" in parameters:
        return {"device_id": unit_id}
    if "slave" in parameters:
        return {"slave": unit_id}
    return {"unit": unit_id}


def _call_read(client, function: int, address: int, count: int, unit_id: int):
    if function not in FUNCTIONS:
        raise InspectorError("Unterstützt werden die Funktionscodes FC01 bis FC04.")
    method = getattr(client, FUNCTIONS[function][1])
    kwargs: dict[str, Any] = {"address": address, "count": count}
    kwargs.update(_unit_kw(method, unit_id))
    return method(**kwargs)


def _safe_value(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    if isinstance(value, int) and abs(value) > 9_007_199_254_740_991:
        return str(value)
    return value


def _bytes_for_order(registers: list[int], order: str) -> bytes:
    base = b"".join(int(register & 0xFFFF).to_bytes(2, "big") for register in registers)
    labels = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[: len(base)]
    if order not in ORDERS.get(len(base), (labels,)):
        raise InspectorError(f"Byte-Reihenfolge {order} passt nicht zum Datentyp.")
    mapping = {label: base[index] for index, label in enumerate(labels)}
    return bytes(mapping[label] for label in order)


def decode_selected(registers: list[int], data_type: str, order: str | None = None) -> Any:
    data_type = str(data_type).lower()
    if data_type == "bool":
        return bool(registers[0])
    if data_type not in TYPE_COUNTS:
        raise InspectorError(f"Unbekannter Datentyp: {data_type}")
    count = TYPE_COUNTS[data_type]
    if len(registers) < count:
        raise InspectorError("Zu wenige Register für den gewählten Datentyp.")
    raw = registers[:count]
    byte_count = count * 2
    if order is None:
        order = ORDERS[byte_count][0]
    data = _bytes_for_order(raw, order)
    formats = {
        "uint16": ">H",
        "int16": ">h",
        "uint32": ">I",
        "int32": ">i",
        "float32": ">f",
        "uint64": ">Q",
        "int64": ">q",
        "float64": ">d",
    }
    return _safe_value(struct.unpack(formats[data_type], data)[0])


def decode_registers(registers: list[int]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "raw_hex": [f"0x{value & 0xFFFF:04X}" for value in registers],
        "groups": [],
    }
    if registers:
        rows = []
        for order in ORDERS[2]:
            rows.extend(
                [
                    {"type": "UInt16", "data_type": "uint16", "order": order, "value": decode_selected(registers, "uint16", order)},
                    {"type": "Int16", "data_type": "int16", "order": order, "value": decode_selected(registers, "int16", order)},
                ]
            )
        result["groups"].append({"label": "16-Bit", "count": 1, "rows": rows})
    if len(registers) >= 2:
        rows = []
        for order in ORDERS[4]:
            for data_type, label in (("uint32", "UInt32"), ("int32", "Int32"), ("float32", "Float32")):
                rows.append({"type": label, "data_type": data_type, "order": order, "value": decode_selected(registers, data_type, order)})
        result["groups"].append({"label": "32-Bit", "count": 2, "rows": rows})
    if len(registers) >= 4:
        rows = []
        for order in ORDERS[8]:
            for data_type, label in (("uint64", "UInt64"), ("int64", "Int64"), ("float64", "Float64")):
                rows.append({"type": label, "data_type": data_type, "order": order, "value": decode_selected(registers, data_type, order)})
        result["groups"].append({"label": "64-Bit", "count": 4, "rows": rows})
    return result


def _match_order_score(register_count: int, order: str) -> float:
    if register_count == 1:
        return 100.0 if order == "AB" else 65.0
    return {
        "ABCD": 100.0,
        "CDAB": 94.0,
        "BADC": 78.0,
        "DCBA": 70.0,
        "ABCDEFGH": 100.0,
        "GHEFCDAB": 92.0,
        "BADCFEHG": 76.0,
        "HGFEDCBA": 68.0,
    }.get(order, 65.0)


def _match_factor_score(factor: float) -> float:
    if factor in (1.0, 0.1, 0.01, 0.001, 0.0001):
        return 100.0
    if factor in (0.00001, 10.0, 100.0, 1000.0):
        return 96.0
    if factor == 0.000001:
        return 92.0
    return 86.0


def _match_reasons(
    quantity_kind: str,
    expected: float,
    data_type: str,
    register_count: int,
    order: str,
    deviation_percent: float,
    tolerance: float,
    polarity_mismatch: bool = False,
) -> list[str]:
    reasons: list[str] = []
    if polarity_mismatch and deviation_percent <= tolerance:
        reasons.append(
            f"Betrag passt ({deviation_percent:.3f} %); Vorzeichen ist entgegengesetzt – Energieflussrichtung prüfen."
        )
    elif deviation_percent <= tolerance:
        reasons.append(f"Messwert liegt innerhalb der Toleranz ({deviation_percent:.3f} %).")
    if quantity_kind == "power" and data_type == "int32":
        reasons.append("SINT32 passt zu einer vorzeichenbehafteten Leistung.")
    elif quantity_kind == "energy" and data_type == "uint32":
        reasons.append("UINT32 ist typisch für einen positiven Zählerstand.")
    elif expected < 0 and data_type.startswith("uint"):
        reasons.append("Vorzeichenloser Datentyp passt schlecht zu einem negativen Sollwert.")
    elif register_count == 2:
        reasons.append("32-Bit-Messwert über zwei zusammenhängende Register.")
    elif register_count == 1 and quantity_kind in ("power", "energy"):
        reasons.append("Nur 16 Bit; bei Energie- und Leistungswerten weniger typisch.")

    if order in ("AB", "ABCD", "ABCDEFGH"):
        reasons.append(f"Standard-Reihenfolge {order}.")
    elif order in ("BA", "BADC", "DCBA", "BADCFEHG", "HGFEDCBA"):
        reasons.append(f"Byte-Tausch {order}; als Zufallstreffer kritischer prüfen.")
    else:
        reasons.append(f"Word-Reihenfolge {order} ist bei Modbus gebräuchlich.")
    return reasons[:3]


def _match_confidence_label(score: float) -> str:
    if score >= 88:
        return "hoch"
    if score >= 72:
        return "mittel"
    return "niedrig"


def _candidate_group_key(item: dict[str, Any]) -> tuple[Any, ...]:
    value_key = f"{float(item['value']):.12g}"
    return (
        item["address"],
        item["register_count"],
        f"{float(item['factor']):.12g}",
        value_key,
    )


def _annotate_width_ambiguities(candidates: list[dict[str, Any]], expected: float) -> None:
    """Mark equal 16/32-bit interpretations without pretending certainty.

    A 32-bit integer with a zero high word naturally contains the same number
    in its low 16-bit register. If both interpretations are similarly
    plausible, prefer the complete 32-bit candidate for ranking while making
    the ambiguity visible to the user.
    """
    value_epsilon = max(abs(expected), 1.0) * 1e-9
    for candidate in candidates:
        candidate["base_confidence"] = candidate["confidence"]
        candidate["ranking_score"] = candidate["confidence"]
        candidate["width_ambiguous"] = False

    for narrow in candidates:
        if narrow["register_count"] != 1 or not narrow["within_tolerance"]:
            continue
        compatible = []
        for wide in candidates:
            if wide["register_count"] != 2 or not wide["within_tolerance"]:
                continue
            if wide["address"] not in (narrow["address"] - 1, narrow["address"]):
                continue
            if wide["factor"] != narrow["factor"]:
                continue
            if abs(float(wide["value"]) - float(narrow["value"])) > value_epsilon:
                continue
            if abs(float(wide["base_confidence"]) - float(narrow["base_confidence"])) > 10.0:
                continue
            compatible.append(wide)
        if not compatible:
            continue

        preferred = max(
            compatible,
            key=lambda item: (
                item["base_confidence"],
                1 if item["order"] == "ABCD" else 0,
                -item["address"],
            ),
        )
        narrow["width_ambiguous"] = True
        narrow["width_alternative_address"] = preferred["address"]
        narrow["width_alternative_type"] = preferred["visu_type"]
        narrow["ranking_score"] = min(narrow["base_confidence"], preferred["base_confidence"] - 1.0)
        narrow["confidence"] = min(narrow["confidence"], 84.0)
        narrow["confidence_label"] = _match_confidence_label(narrow["confidence"])
        narrow["reasons"].insert(
            1,
            f"Identischer Teilwert eines möglichen 32-Bit-Datenpunkts ab Register {preferred['address']}.",
        )
        narrow["reasons"] = narrow["reasons"][:3]

        for wide in compatible:
            wide["width_ambiguous"] = True
            wide["width_alternative_address"] = narrow["address"]
            wide["width_alternative_type"] = narrow["visu_type"]
            wide["confidence"] = min(wide["confidence"], 87.0)
            wide["confidence_label"] = _match_confidence_label(wide["confidence"])
            note = f"Der Wert erscheint zugleich als 16-Bit-Teilregister {narrow['address']}; 32-Bit wird vollständig bevorzugt."
            if note not in wide["reasons"]:
                wide["reasons"].insert(1, note)
                wide["reasons"] = wide["reasons"][:3]


def match_register_values(payload: dict[str, Any]) -> dict[str, Any]:
    """Rank interpretations at every offset by distance to a known field value.

    This only interprets raw values supplied by a previous read. It performs no
    additional Modbus request and deliberately labels the result as candidates:
    mathematical proximity alone cannot prove a register's semantic meaning.
    """
    raw_registers = payload.get("registers")
    if not isinstance(raw_registers, list) or not raw_registers:
        raise InspectorError("Zuerst einen Registerbereich lesen.")
    if len(raw_registers) > 125:
        raise InspectorError("Für die Zielwertsuche sind höchstens 125 Register erlaubt.")
    registers = [_int(value, "Registerwert", 0, 65535) for value in raw_registers]
    start_address = _int(payload.get("start_address", 0), "Startadresse", 0, 65535)
    expected = _float(payload.get("expected_value"), "Erwarteter Wert", -1e15, 1e15)
    if not math.isfinite(expected):
        raise InspectorError("Der erwartete Wert muss endlich sein.")
    tolerance = _float(payload.get("tolerance_percent", 10), "Toleranz", 0, 1000)
    mode = str(payload.get("type_mode", "auto")).strip().lower()
    if mode not in MATCH_TYPE_MODES:
        raise InspectorError("Unbekannte Datentyp-Auswahl.")
    quantity_kind = str(payload.get("quantity_kind", "free")).strip().lower()
    if quantity_kind not in QUANTITY_TYPE_SCORES:
        raise InspectorError("Unbekannte Messgrösse.")
    limit = _int(payload.get("limit", 20), "Trefferanzahl", 1, 100)

    factors = list(MATCH_FACTORS)
    custom_factor_value = payload.get("custom_factor")
    if custom_factor_value not in (None, ""):
        custom_factor = _float(custom_factor_value, "Zusatzfaktor", -1e12, 1e12)
        if custom_factor == 0:
            raise InspectorError("Der Zusatzfaktor darf nicht 0 sein.")
        if custom_factor not in factors:
            factors.append(custom_factor)

    candidates: list[dict[str, Any]] = []
    denominator = max(abs(expected), 1.0)
    for offset in range(len(registers)):
        for data_type in MATCH_TYPE_MODES[mode]:
            count = TYPE_COUNTS[data_type]
            if offset + count > len(registers):
                continue
            orders = ORDERS[count * 2]
            for order in orders:
                raw_value = decode_selected(registers[offset : offset + count], data_type, order)
                if not isinstance(raw_value, (int, float)) or not math.isfinite(float(raw_value)):
                    continue
                for factor in factors:
                    scaled = float(raw_value) * factor
                    if not math.isfinite(scaled):
                        continue
                    direct_difference = abs(scaled - expected)
                    magnitude_difference = abs(abs(scaled) - abs(expected))
                    polarity_mismatch = (
                        quantity_kind == "power"
                        and expected != 0
                        and scaled != 0
                        and (scaled < 0) != (expected < 0)
                        and magnitude_difference < direct_difference
                    )
                    difference = magnitude_difference if polarity_mismatch else direct_difference
                    deviation_percent = difference / denominator * 100
                    within_tolerance = deviation_percent <= tolerance
                    if tolerance > 0:
                        proximity_score = max(0.0, 100.0 - (deviation_percent / tolerance * 100.0))
                    else:
                        proximity_score = 100.0 if difference == 0 else 0.0
                    type_score = float(QUANTITY_TYPE_SCORES[quantity_kind][data_type])
                    if expected < 0 and data_type.startswith("uint"):
                        type_score = min(type_score, 10.0)
                    order_score = _match_order_score(count, order)
                    factor_score = _match_factor_score(factor)
                    alignment_score = 100.0 if count == 1 or (start_address + offset) % 2 == 0 else 90.0
                    confidence = round(
                        proximity_score * 0.30
                        + type_score * 0.40
                        + order_score * 0.18
                        + factor_score * 0.07
                        + alignment_score * 0.05,
                        1,
                    )
                    candidates.append(
                        {
                            "address": start_address + offset,
                            "offset": offset,
                            "register_count": count,
                            "type": MATCH_LABELS[data_type],
                            "data_type": data_type,
                            "order": order,
                            "raw_value": _safe_value(raw_value),
                            "factor": factor,
                            "value": _safe_value(scaled),
                            "difference": difference,
                            "direct_difference": direct_difference,
                            "deviation_percent": deviation_percent,
                            "within_tolerance": within_tolerance,
                            "polarity_mismatch": polarity_mismatch,
                            "confidence": confidence,
                            "confidence_label": _match_confidence_label(confidence),
                            "visu_type": VISU_TYPES[data_type],
                            "reasons": _match_reasons(
                                quantity_kind,
                                expected,
                                data_type,
                                count,
                                order,
                                deviation_percent,
                                tolerance,
                                polarity_mismatch,
                            ),
                        }
                    )

    _annotate_width_ambiguities(candidates, expected)

    type_priority = {name: index for index, name in enumerate(MATCH_TYPE_MODES[mode])}
    factor_priority = {factor: index for index, factor in enumerate(factors)}
    candidates.sort(
        key=lambda item: (
            0 if item["within_tolerance"] else 1,
            -item["ranking_score"] if item["within_tolerance"] else item["deviation_percent"],
            item["deviation_percent"] if item["within_tolerance"] else -item["confidence"],
            item["address"],
            type_priority[item["data_type"]],
            factor_priority[item["factor"]],
            item["order"],
        )
    )

    # Equivalent signed/unsigned interpretations and repeated orders can
    # produce the same engineering value. Keep the strongest interpretation
    # instead of filling the result list with clones.
    grouped: dict[tuple[Any, ...], dict[str, Any]] = {}
    for candidate in candidates:
        key = _candidate_group_key(candidate)
        label = f"{candidate['type']} · {candidate['order']}"
        if key not in grouped:
            grouped[key] = candidate
            grouped[key]["equivalent_interpretations"] = []
        elif label != f"{grouped[key]['type']} · {grouped[key]['order']}":
            grouped[key]["equivalent_interpretations"].append(label)
    unique_candidates = list(grouped.values())
    selected = unique_candidates[:limit]
    return {
        "ok": True,
        "expected_value": expected,
        "tolerance_percent": tolerance,
        "quantity_kind": quantity_kind,
        "checked_registers": len(registers),
        "candidate_count": len(candidates),
        "unique_candidate_count": len(unique_candidates),
        "within_tolerance": sum(1 for item in unique_candidates if item["within_tolerance"]),
        "ambiguous_candidates": sum(1 for item in unique_candidates if item.get("width_ambiguous")),
        "recommendation": selected[0] if selected and selected[0]["within_tolerance"] else None,
        "matches": selected,
    }


def list_interfaces() -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    if psutil is not None:
        try:
            interface_map = psutil.net_if_addrs()
        except (OSError, PermissionError):
            interface_map = {}
        for name, addresses in interface_map.items():
            for address in addresses:
                if address.family != socket.AF_INET or not address.address:
                    continue
                try:
                    interface = ipaddress.ip_interface(f"{address.address}/{address.netmask or '255.255.255.0'}")
                except ValueError:
                    continue
                found.append(
                    {
                        "name": name,
                        "address": address.address,
                        "netmask": address.netmask or "",
                        "cidr": str(interface.network),
                    }
                )
    if not found:
        try:
            host = socket.gethostbyname(socket.gethostname())
            found.append({"name": "Standard", "address": host, "netmask": "", "cidr": f"{host}/24"})
        except socket.gaierror:
            pass
    return found


def connect_test(payload: dict[str, Any]) -> dict[str, Any]:
    target = _target(payload)
    started = time.perf_counter()
    client = _client(target)
    try:
        connected = bool(client.connect())
    except (OSError, ModbusException) as error:
        raise InspectorError(f"Verbindung fehlgeschlagen: {error}", 502)
    finally:
        client.close()
    if not connected:
        raise InspectorError("Keine TCP-Verbindung zum Zielgerät.", 502)
    return {
        "ok": True,
        "host": target.host,
        "port": target.port,
        "transport": target.transport,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


# Small curated subset of the public IEEE MA-L (OUI) registry
# (https://standards-oui.ieee.org/oui/oui.txt), limited to vendors relevant to
# building-automation/industrial/network gear. Best-effort only, not exhaustive.
_OUI_VENDORS: dict[str, str] = {
    "00:00:0A": "Omron",
    "00:00:54": "Schneider Electric",
    "00:01:05": "Beckhoff Automation",
    "00:02:01": "ifm electronic",
    "00:03:74": "Schneider Electric",
    "00:03:AC": "Fronius",
    "00:06:6E": "Delta Electronics",
    "00:06:77": "SICK",
    "00:07:46": "Turck",
    "00:07:68": "Danfoss",
    "00:0A:66": "Mitsubishi Electric",
    "00:0A:B3": "Gira",
    "00:0B:2D": "Danfoss",
    "00:0B:AB": "Advantech",
    "00:0C:81": "Schneider Electric",
    "00:0D:81": "Pepperl+Fuchs",
    "00:0E:02": "Advantech",
    "00:0E:F0": "Festo",
    "00:10:8D": "Johnson Controls",
    "00:11:00": "Schneider Electric",
    "00:11:06": "Siemens",
    "00:12:93": "ABB",
    "00:13:24": "Schneider Electric",
    "00:13:86": "ABB",
    "00:14:53": "Advantech",
    "00:15:7E": "Weidmüller",
    "00:15:BB": "SMA Solar Technology",
    "00:18:23": "Delta Electronics",
    "00:19:09": "Danfoss",
    "00:19:43": "Belden",
    "00:1B:08": "Danfoss",
    "00:1B:45": "ABB",
    "00:1F:55": "Honeywell",
    "00:20:3D": "Honeywell",
    "00:22:09": "Omron",
    "00:26:92": "Mitsubishi Electric",
    "00:27:02": "SolarEdge",
    "00:27:19": "TP-Link",
    "00:30:DE": "WAGO",
    "00:40:84": "Honeywell",
    "00:50:1E": "Belden",
    "00:80:2F": "National Instruments",
    "00:80:A7": "Honeywell",
    "00:90:30": "Honeywell",
    "00:90:40": "Siemens",
    "00:90:E8": "Moxa",
    "00:A0:03": "Siemens",
    "00:A0:45": "Phoenix Contact",
    "00:B0:09": "Belden",
    "00:D0:26": "Hirschmann (Belden)",
    "00:D0:8E": "Belden",
    "00:D0:C9": "Advantech",
    "0C:23:69": "Honeywell",
    "10:4B:46": "Mitsubishi Electric",
    "14:41:46": "Honeywell",
    "18:97:F1": "Kostal",
    "20:44:3A": "Schneider Electric",
    "20:F8:5E": "Delta Electronics",
    "24:0B:B1": "Kostal",
    "24:5A:4C": "Ubiquiti",
    "28:9E:DF": "Danfoss",
    "28:CD:C1": "Raspberry Pi Foundation",
    "28:E9:8E": "Mitsubishi Electric",
    "2C:CF:67": "Raspberry Pi Foundation",
    "30:BE:3B": "Mitsubishi Electric",
    "30:CB:36": "Belden",
    "34:E8:94": "TP-Link",
    "34:F7:16": "TP-Link",
    "38:4B:24": "Siemens",
    "38:E0:8E": "Mitsubishi Electric",
    "3C:F7:D1": "Omron",
    "48:1B:A4": "Cisco",
    "50:00:84": "Siemens",
    "50:0B:88": "Moxa",
    "50:31:AD": "ABB",
    "50:4F:94": "Loxone",
    "54:44:3B": "Huawei",
    "54:A7:03": "TP-Link",
    "54:F8:76": "ABB",
    "58:52:8A": "Mitsubishi Electric",
    "58:57:0D": "Danfoss",
    "58:FC:C8": "Honeywell",
    "5C:8D:E5": "Delta Electronics",
    "5C:CA:32": "Theben",
    "60:22:32": "Ubiquiti",
    "60:39:1F": "ABB",
    "64:60:38": "Hirschmann (Belden)",
    "6C:03:B5": "Cisco",
    "74:0B:B0": "Hirschmann (Belden)",
    "74:73:1D": "ifm electronic",
    "74:83:C2": "Ubiquiti",
    "74:F6:61": "Schneider Electric",
    "74:FE:48": "Advantech",
    "78:52:49": "Loxone",
    "78:8A:20": "Ubiquiti",
    "80:2A:A8": "Ubiquiti",
    "80:B5:C6": "Omron",
    "84:C3:E8": "Vaillant",
    "84:D6:C5": "SolarEdge",
    "88:A2:9E": "Raspberry Pi Foundation",
    "90:DA:F9": "Siemens",
    "94:59:07": "Belden",
    "94:67:7E": "Belden",
    "94:A4:B5": "Mitsubishi Electric",
    "94:AE:E3": "Hirschmann (Belden)",
    "94:D9:B3": "TP-Link",
    "94:E6:86": "Espressif (ESP32/ESP8266)",
    "94:FC:87": "Hirschmann (Belden)",
    "98:FE:54": "Raspberry Pi Foundation",
    "9C:0E:51": "Schneider Electric",
    "A0:26:05": "Hirschmann (Belden)",
    "A0:B0:86": "Hirschmann (Belden)",
    "A8:74:1D": "Phoenix Contact",
    "AC:19:9F": "Sungrow",
    "AC:B1:81": "Belden",
    "B0:49:5F": "Omron",
    "B0:95:8E": "TP-Link",
    "B0:BE:76": "TP-Link",
    "B4:8A:0A": "Espressif (ESP32/ESP8266)",
    "B8:27:EB": "Raspberry Pi Foundation",
    "B8:74:24": "Viessmann",
    "C0:25:E9": "TP-Link",
    "C4:00:AD": "Advantech",
    "C4:B1:6B": "Advantech",
    "CC:7E:0F": "Theben",
    "CC:82:7F": "Advantech",
    "CC:CC:EA": "Phoenix Contact",
    "D4:8A:FC": "Espressif (ESP32/ESP8266)",
    "D8:3A:DD": "Raspberry Pi Foundation",
    "D8:DA:F1": "Huawei",
    "DC:A6:32": "Raspberry Pi Foundation",
    "E0:06:30": "Huawei",
    "E0:63:DA": "Ubiquiti",
    "E0:DC:A0": "Siemens",
    "E4:38:83": "Ubiquiti",
    "E4:5F:01": "Raspberry Pi Foundation",
    "E4:65:B8": "Espressif (ESP32/ESP8266)",
    "E8:0A:B9": "Cisco",
    "EC:1C:5D": "Siemens",
    "EC:E5:55": "Hirschmann (Belden)",
    "F0:7F:0C": "Kostal",
    "F0:9F:C2": "Ubiquiti",
    "F0:C1:CE": "GoodWe",
}


def _probe_port(host: str, port: int, timeout: float) -> dict[str, Any] | None:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {
                "host": host,
                "port": port,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
    except OSError:
        return None


def _probe_modbus(host: str, port: int, timeout: float) -> bool:
    """Best-effort check that an open TCP port actually speaks Modbus.

    A plain port scan cannot tell a Modbus gateway from any other service
    bound to the same port. A real Modbus exception response still proves the
    protocol, so only a connection failure or a garbled reply counts as "not
    Modbus".
    """
    if ModbusTcpClient is None:
        return False
    client = ModbusTcpClient(host, port=port, timeout=timeout)
    try:
        if not client.connect():
            return False
        kwargs = _unit_kw(client.read_holding_registers, 1)
        response = client.read_holding_registers(address=0, count=1, **kwargs)
        return response is not None
    except (OSError, ModbusException):
        return False
    finally:
        client.close()


def _resolve_hostname(host: str) -> str | None:
    try:
        return socket.gethostbyaddr(host)[0]
    except (OSError, socket.herror, socket.gaierror):
        return None


def _read_arp_table() -> dict[str, str]:
    """Read the OS ARP/neighbor cache so scan hits can show a MAC address.

    Only consults the cache the OS already maintains (from earlier
    ICMP/ARP/TCP traffic on the local segment) - it does not send any
    extra probes of its own and returns nothing for hosts reached over a
    routed VPN link, which have no local ARP entry.
    """
    table: dict[str, str] = {}
    try:
        if sys.platform.startswith("win"):
            output = subprocess.run(
                ["arp", "-a"], capture_output=True, text=True, timeout=3, check=False,
            ).stdout
            for line in output.splitlines():
                match = re.match(
                    r"\s*(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+\w+",
                    line,
                )
                if match:
                    table[match.group(1)] = match.group(2).replace("-", ":").upper()
        else:
            output = subprocess.run(
                ["ip", "neigh"], capture_output=True, text=True, timeout=3, check=False,
            ).stdout
            for line in output.splitlines():
                parts = line.split()
                if len(parts) >= 5 and "lladdr" in parts:
                    table[parts[0]] = parts[parts.index("lladdr") + 1].upper()
    except (OSError, subprocess.SubprocessError):
        pass
    return table


def _vendor_for_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    return _OUI_VENDORS.get(mac.upper().replace("-", ":")[:8])


def scan_network(payload: dict[str, Any]) -> dict[str, Any]:
    cidr = str(payload.get("cidr", "")).strip()
    try:
        network = ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        raise InspectorError("Bitte einen gültigen IPv4-Bereich eingeben, z. B. 192.168.1.0/24.")
    if network.version != 4:
        raise InspectorError("Die erste Version unterstützt beim Netzwerkscan nur IPv4.")
    public_allowed = os.getenv("HBMODBUS_ALLOW_PUBLIC") == "1"
    if not public_allowed and not (network.is_private or network.is_loopback or network.is_link_local):
        raise InspectorError("Aus Sicherheitsgründen können nur lokale/private Netze gescannt werden.")
    if network.num_addresses > 256:
        raise InspectorError("Pro Scan sind höchstens 256 Adressen erlaubt (/24).")
    port = _int(payload.get("port", 502), "Port", 1, 65535)
    timeout_ms = _int(payload.get("timeout_ms", 250), "Timeout", 30, 5000)
    workers = _int(payload.get("workers", 48), "Parallelität", 1, 96)
    verify_modbus = bool(payload.get("verify_modbus"))
    resolve_names = bool(payload.get("resolve_names"))
    hosts = [str(host) for host in network.hosts()]
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(hosts)))) as executor:
        futures = {executor.submit(_probe_port, host, port, timeout_ms / 1000): host for host in hosts}
        for future in as_completed(futures):
            item = future.result()
            if item:
                results.append(item)
    results.sort(key=lambda item: ipaddress.ip_address(item["host"]))

    for item in results:
        item["modbus_verified"] = None
        item["hostname"] = None

    if results and (verify_modbus or resolve_names):
        modbus_timeout = max(timeout_ms, 500) / 1000
        jobs: dict[Any, tuple[dict[str, Any], str]] = {}
        with ThreadPoolExecutor(max_workers=min(workers, max(1, len(results) * 2))) as executor:
            for item in results:
                if verify_modbus:
                    future = executor.submit(_probe_modbus, item["host"], port, modbus_timeout)
                    jobs[future] = (item, "modbus_verified")
                if resolve_names:
                    future = executor.submit(_resolve_hostname, item["host"])
                    jobs[future] = (item, "hostname")
            for future in as_completed(jobs):
                item, key = jobs[future]
                try:
                    item[key] = future.result()
                except Exception:
                    pass

    if results:
        arp_table = _read_arp_table()
        for item in results:
            mac = arp_table.get(item["host"])
            item["mac"] = mac
            item["vendor"] = _vendor_for_mac(mac)
    for item in results:
        item.setdefault("mac", None)
        item.setdefault("vendor", None)

    return {
        "ok": True,
        "cidr": str(network),
        "scanned": len(hosts),
        "verify_modbus": verify_modbus,
        "resolve_names": resolve_names,
        "modbus_confirmed": sum(1 for item in results if item.get("modbus_verified")) if verify_modbus else None,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "devices": results,
    }


def _read_payload(payload: dict[str, Any]) -> tuple[Target, int, int, int, int]:
    target = _target(payload)
    unit_id = _int(payload.get("unit_id", 1), "Unit-ID (Slave-ID)", 0, 247)
    function = _int(payload.get("function", 3), "Funktionscode", 1, 4)
    address = _int(payload.get("address", 0), "Registeradresse", 0, 65535)
    max_count = 2000 if function in (1, 2) else 125
    count = _int(payload.get("count", 4), "Anzahl", 1, max_count)
    return target, unit_id, function, address, count


def read_values(payload: dict[str, Any]) -> dict[str, Any]:
    target, unit_id, function, address, count = _read_payload(payload)
    client = _client(target)
    try:
        if not client.connect():
            raise InspectorError("Keine TCP-Verbindung zum Zielgerät.", 502)
        response = _call_read(client, function, address, count, unit_id)
    except InspectorError:
        raise
    except (OSError, ModbusException) as error:
        raise InspectorError(f"Modbus-Abfrage fehlgeschlagen: {error}", 502)
    finally:
        client.close()
    if response is None:
        raise InspectorError("Das Gerät hat nicht geantwortet.", 504)
    if response.isError():
        code = getattr(response, "exception_code", "unbekannt")
        raise InspectorError(f"Modbus-Ausnahme vom Gerät (Code {code}).", 502)

    if function in (1, 2):
        values = [bool(value) for value in response.bits[:count]]
        decoding = {"bits": values}
    else:
        values = [int(value) for value in response.registers[:count]]
        decoding = decode_registers(values)
    return {
        "ok": True,
        "unit_id": unit_id,
        "function": function,
        "function_name": FUNCTIONS[function][0],
        "transport": target.transport,
        "address": address,
        "count": count,
        "values": values,
        "decoding": decoding,
        "timestamp": time.time(),
    }


def scan_unit_ids(payload: dict[str, Any]) -> dict[str, Any]:
    target = _target(payload)
    start_id = _int(payload.get("start_id", 1), "Start-ID", 0, 247)
    end_id = _int(payload.get("end_id", 20), "End-ID", 0, 247)
    if end_id < start_id:
        raise InspectorError("Die End-ID muss grösser oder gleich der Start-ID sein.")
    function = _int(payload.get("function", 3), "Funktionscode", 1, 4)
    address = _int(payload.get("address", 0), "Testadresse", 0, 65535)
    found: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    fingerprints: list[str] = []
    started = time.perf_counter()
    for unit_id in range(start_id, end_id + 1):
        unit_started = time.perf_counter()
        client = _client(target)
        try:
            if not client.connect():
                latency = round((time.perf_counter() - unit_started) * 1000, 1)
                attempts.append({"unit_id": unit_id, "status": "connection_error", "detail": "TCP-Verbindung fehlgeschlagen", "latency_ms": latency})
                continue
            try:
                response = _call_read(client, function, address, 1, unit_id)
                latency = round((time.perf_counter() - unit_started) * 1000, 1)
                if response is None:
                    attempts.append({"unit_id": unit_id, "status": "no_response", "detail": "Keine Modbus-Antwort", "latency_ms": latency})
                    continue
                if response.isError():
                    code = getattr(response, "exception_code", None)
                    if code is None:
                        detail = str(response) or response.__class__.__name__
                        attempts.append({"unit_id": unit_id, "status": "no_response", "detail": f"Keine Antwort: {detail}", "latency_ms": latency})
                    elif int(code) in (10, 11):
                        attempts.append({"unit_id": unit_id, "status": "gateway_error", "detail": f"Gateway-Exception {code}: Ziel nicht erreichbar", "latency_ms": latency})
                    else:
                        item = {"unit_id": unit_id, "status": "exception", "detail": f"Modbus-Exception {code} – Unit/Slave antwortet", "latency_ms": latency}
                        attempts.append(item)
                        found.append(item)
                        fingerprints.append(f"E{code}")
                else:
                    raw = response.bits[:1] if function in (1, 2) else response.registers[:1]
                    item = {"unit_id": unit_id, "status": "answer", "detail": f"Antwort · Rohwert {raw[0]}" if raw else "Gültige Modbus-Antwort", "latency_ms": latency}
                    attempts.append(item)
                    found.append(item)
                    fingerprints.append(f"V{raw}")
            except (OSError, ModbusException) as error:
                latency = round((time.perf_counter() - unit_started) * 1000, 1)
                detail = str(error).strip() or error.__class__.__name__
                attempts.append({"unit_id": unit_id, "status": "timeout", "detail": f"Keine Antwort: {detail}", "latency_ms": latency})
                continue
        finally:
            client.close()
    warning = None
    if len(found) >= 8 and len(set(fingerprints)) == 1:
        warning = "Viele Unit-IDs (Slave-IDs) liefern dieselbe Antwort. Das Gateway könnte die Unit-ID ignorieren."
    elif not found:
        warning = (
            "Der TCP-Port ist erreichbar, aber es kam keine gültige Modbus-Antwort. "
            "Mögliche Ursachen: falsche Übertragungsart (TCP statt RTU über TCP), ein anderer aktiver Bus-Master, "
            "falsche Testadresse/Funktion oder Timeout über VPN."
        )
    return {
        "ok": True,
        "scanned": end_id - start_id + 1,
        "found": found,
        "attempts": attempts,
        "warning": warning,
        "duration_ms": round((time.perf_counter() - started) * 1000),
    }


def scan_registers(payload: dict[str, Any]) -> dict[str, Any]:
    """Search a bounded range and retry rejected addresses as register blocks.

    Some Modbus devices expose values only when a complete manufacturer block
    is requested. A one-register probe then returns exception 2 even though
    the documented start address is valid. Probe bounded common block widths.
    """
    target = _target(payload)
    unit_id = _int(payload.get("unit_id", 1), "Unit-ID (Slave-ID)", 0, 247)
    requested_function = _int(payload.get("function", 0), "Funktionsauswahl", 0, 4)
    if requested_function not in (0, 3, 4):
        raise InspectorError("Die Registersuche unterstützt FC03, FC04 oder beide.")
    functions = (3, 4) if requested_function == 0 else (requested_function,)
    start_address = _int(payload.get("start_address", 0), "Startadresse", 0, 65535)
    end_address = _int(payload.get("end_address", 99), "Endadresse", 0, 65535)
    if end_address < start_address:
        raise InspectorError("Die Endadresse muss grösser oder gleich der Startadresse sein.")
    if end_address - start_address + 1 > 512:
        raise InspectorError("Pro Suche sind höchstens 512 Adressen erlaubt. Bitte den Bereich aufteilen.")
    capture_end_address = _int(
        payload.get("capture_end_address", end_address),
        "Ergebnis-Endadresse",
        end_address,
        65535,
    )
    delay_ms = _int(payload.get("delay_ms", 50), "Abfragepause", 0, 2000)

    found_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    unsupported = 0
    checked = 0
    requests = 0
    block_retry_count = 0
    block_hits = 0
    blocks: list[dict[str, int]] = []
    aborted = False
    started = time.perf_counter()
    client = _client(target)
    try:
        if not client.connect():
            raise InspectorError("Keine TCP-Verbindung zum Zielgerät.", 502)
        consecutive_io_errors = 0
        for function in functions:
            for address in range(start_address, end_address + 1):
                checked += 1
                existing_block_value = found_by_key.get((function, address))
                if existing_block_value and int(existing_block_value.get("read_count", 1)) > 1:
                    continue
                try:
                    requests += 1
                    response = _call_read(client, function, address, 1, unit_id)
                    if response is None:
                        raise ModbusException("Keine Antwort")
                    if response.isError():
                        code = getattr(response, "exception_code", None)
                        if code == 2:
                            block_response = None
                            block_width = 0
                            for width in (2, 4, 6, 8):
                                if address + width - 1 > 65535:
                                    continue
                                block_retry_count += 1
                                requests += 1
                                try:
                                    candidate_response = _call_read(client, function, address, width, unit_id)
                                except (OSError, ModbusException) as retry_error:
                                    errors.append({
                                        "function": function,
                                        "address": address,
                                        "error": f"{width}-Register-Test: {str(retry_error).strip() or retry_error.__class__.__name__}",
                                    })
                                    continue
                                if candidate_response is not None and not candidate_response.isError():
                                    candidate_registers = getattr(candidate_response, "registers", [])
                                    if len(candidate_registers) >= width:
                                        block_response = candidate_response
                                        block_width = width
                                        break
                            block_registers = [] if block_response is None else getattr(block_response, "registers", [])
                            if block_width and len(block_registers) >= block_width:
                                block_hits += 1
                                blocks.append({"function": function, "start": address, "count": block_width})
                                for offset, raw_value in enumerate(block_registers[:block_width]):
                                    register_address = address + offset
                                    if register_address > capture_end_address:
                                        continue
                                    value = int(raw_value) & 0xFFFF
                                    found_by_key[(function, register_address)] = {
                                        "function": function,
                                        "address": register_address,
                                        "value": value,
                                        "hex": f"0x{value:04X}",
                                        "read_count": block_width,
                                        "block_start": address,
                                    }
                            else:
                                unsupported += 1
                        else:
                            errors.append({"function": function, "address": address, "error": f"Modbus-Exception {code or 'unbekannt'}"})
                        consecutive_io_errors = 0
                    else:
                        registers = getattr(response, "registers", [])
                        if registers:
                            value = int(registers[0]) & 0xFFFF
                            key = (function, address)
                            existing = found_by_key.get(key)
                            if existing is None or int(existing.get("read_count", 1)) <= 1:
                                found_by_key[key] = {
                                    "function": function,
                                    "address": address,
                                    "value": value,
                                    "hex": f"0x{value:04X}",
                                    "read_count": 1,
                                    "block_start": address,
                                }
                        else:
                            errors.append({"function": function, "address": address, "error": "Leere Modbus-Antwort"})
                        consecutive_io_errors = 0
                except (OSError, ModbusException) as error:
                    consecutive_io_errors += 1
                    errors.append({"function": function, "address": address, "error": str(error).strip() or error.__class__.__name__})
                    if consecutive_io_errors >= 3:
                        aborted = True
                        break
                if delay_ms:
                    time.sleep(delay_ms / 1000)
            if aborted:
                break
    finally:
        client.close()

    found = sorted(found_by_key.values(), key=lambda item: (item["function"], item["address"]))
    warning = None
    if aborted:
        warning = "Nach drei aufeinanderfolgenden Kommunikationsfehlern abgebrochen. Verbindung, Busbelegung und Timeout prüfen."
    elif not found:
        warning = "Im gewählten Bereich antwortet kein Register. Einen anderen Bereich oder FC03/FC04 versuchen."
    elif block_hits:
        warning = (
            f"{block_hits} Mehrregister-Block{' wurde' if block_hits == 1 else 's wurden'} nur mit einer "
            "gemeinsamen Blockabfrage erkannt. Startadresse und Blockgrösse sind in der Tabelle gekennzeichnet."
        )
    return {
        "ok": True,
        "unit_id": unit_id,
        "functions": list(functions),
        "start_address": start_address,
        "end_address": end_address,
        "checked": checked,
        "requests": requests,
        "found": found,
        "unsupported": unsupported,
        "block_retry_count": block_retry_count,
        "block_hits": block_hits,
        "blocks": blocks,
        "errors": errors,
        "aborted": aborted,
        "warning": warning,
        "duration_ms": round((time.perf_counter() - started) * 1000),
        "timestamp": time.time(),
    }


def poll_points(payload: dict[str, Any]) -> dict[str, Any]:
    target = _target(payload)
    points = payload.get("points")
    if not isinstance(points, list) or not points:
        raise InspectorError("Es wurden keine Monitorpunkte übergeben.")
    if len(points) > 100:
        raise InspectorError("Pro Abfrage sind höchstens 100 Monitorpunkte erlaubt.")

    results = []
    read_cache: dict[tuple[int, int, int, int], Any] = {}
    client = _client(target)
    try:
        if not client.connect():
            raise InspectorError("Keine TCP-Verbindung zum Zielgerät.", 502)
        for point in points:
            point_id = str(point.get("id", ""))
            try:
                data_type = str(point.get("data_type", "uint16")).lower()
                function = _int(point.get("function", 3), "Funktionscode", 1, 4)
                address = _int(point.get("address", 0), "Registeradresse", 0, 65535)
                unit_id = _int(point.get("unit_id", 1), "Unit-ID (Slave-ID)", 0, 247)
                logical_count = 1 if function in (1, 2) else TYPE_COUNTS.get(data_type, 1)
                read_start = _int(point.get("read_start", address), "Abfrage-Startadresse", 0, 65535)
                read_count = _int(point.get("read_count", logical_count), "Abfrageanzahl", 1, 2000 if function in (1, 2) else 125)
                value_offset = _int(point.get("value_offset", address - read_start), "Wert-Offset", 0, read_count - 1)
                if read_start + read_count > 65536:
                    raise InspectorError("Der gespeicherte Abfrageblock überschreitet die letzte Modbus-Adresse.")
                if read_start + value_offset != address:
                    raise InspectorError("Registeradresse und gespeicherter Wert-Offset passen nicht zusammen.")
                if value_offset + logical_count > read_count:
                    raise InspectorError("Der Datenpunkt liegt nicht vollständig im gespeicherten Abfrageblock.")

                cache_key = (unit_id, function, read_start, read_count)
                if cache_key not in read_cache:
                    read_cache[cache_key] = _call_read(client, function, read_start, read_count, unit_id)
                response = read_cache[cache_key]
                if response is None or response.isError():
                    code = getattr(response, "exception_code", "keine Antwort") if response else "keine Antwort"
                    results.append({"id": point_id, "ok": False, "error": str(code)})
                    continue
                block_raw = response.bits[:read_count] if function in (1, 2) else response.registers[:read_count]
                if len(block_raw) < read_count:
                    results.append({"id": point_id, "ok": False, "error": "Unvollständige Modbus-Antwort"})
                    continue
                raw = block_raw[value_offset : value_offset + logical_count]
                value = bool(raw[0]) if function in (1, 2) else decode_selected([int(item) for item in raw], data_type, point.get("order"))
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    scale = _float(point.get("scale", 1), "Skalierung", -1_000_000, 1_000_000)
                    offset = _float(point.get("offset", 0), "Offset", -1_000_000_000, 1_000_000_000)
                    value = _safe_value(value * scale + offset)
                results.append({
                    "id": point_id,
                    "ok": True,
                    "value": value,
                    "raw": list(raw),
                    "read_start": read_start,
                    "read_count": read_count,
                    "value_offset": value_offset,
                })
            except (InspectorError, OSError, ModbusException, struct.error) as error:
                results.append({"id": point_id, "ok": False, "error": str(error)})
    finally:
        client.close()
    return {"ok": True, "timestamp": time.time(), "points": results}
