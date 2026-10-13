"""Modbus RTU über USB: Verbindungsangaben, RTU-Suche gegen einen simulierten Zähler, Exporte."""

import re
import struct
import sys
import time
import types
import unittest
from unittest import mock

import app as app_module
import modbus_core
from ha_export import build_yaml
from meter_list import build_csv, build_rows, knx_dpt, plausibility
from modbus_core import InspectorError, _target, rtu_probe_timeout_ms

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None


def _crc(frame: bytes) -> bytes:
    crc = 0xFFFF
    for byte in frame:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return struct.pack("<H", crc)


class FakeRtuMeter:
    """Zähler am Bus: antwortet nur bei 19200 Baud, gerader Parität und Unit-ID 7."""

    def __init__(self, unit_id=7, baud=19200, parity="E"):
        self.unit_id, self.baud, self.parity = unit_id, baud, parity
        self.registers = {0: 2305, 1: 1234, 2: 0x4248, 3: 0x0000}  # 230,5 V · Rohwert · float32 50.0 (ABCD)
        self.requests = 0
        self.opens = 0

    def answer(self, frame: bytes, baud: int, parity: str) -> bytes:
        self.requests += 1
        if len(frame) != 8 or _crc(frame[:6]) != frame[6:8] or frame[0] != self.unit_id:
            return b""
        if baud != self.baud or parity != self.parity:
            return b""  # falsche Einstellungen: der Zähler versteht die Anfrage nicht
        function, address, count = frame[1], *struct.unpack(">HH", frame[2:6])
        if function not in (3, 4):
            body = bytes([self.unit_id, function | 0x80, 1])
        elif address + count > 4:
            body = bytes([self.unit_id, function | 0x80, 2])
        else:
            values = [self.registers[address + index] for index in range(count)]
            body = bytes([self.unit_id, function, count * 2]) + struct.pack(f">{count}H", *values)
        return body + _crc(body)


METERS: dict[str, FakeRtuMeter] = {}

if serial is not None:
    class FakeMeterSerial(serial.SerialBase):
        """pyserial-Schnittstelle «fakemeter://name», hinter der ein simulierter Zähler hängt."""

        def open(self):
            self.meter = METERS[self.portstr.split("://", 1)[1]]
            self.meter.opens += 1
            self._buffer = b""
            self.is_open = True

        def _reconfigure_port(self, *args, **kwargs):
            pass

        def close(self):
            self.is_open = False

        @property
        def in_waiting(self):
            return len(self._buffer)

        def write(self, data):
            self._buffer += self.meter.answer(bytes(data), self.baudrate, self.parity)
            return len(data)

        def read(self, size=1):
            data, self._buffer = self._buffer[:size], self._buffer[size:]
            if not data and self.timeout:
                time.sleep(min(self.timeout, 0.02))
            return data

        def reset_input_buffer(self):
            self._buffer = b""

        def reset_output_buffer(self):
            pass

        def flush(self):
            pass

    _module = types.ModuleType("ckofakeserial.protocol_fakemeter")
    _module.Serial = FakeMeterSerial
    sys.modules.setdefault("ckofakeserial", types.ModuleType("ckofakeserial"))
    sys.modules["ckofakeserial.protocol_fakemeter"] = _module
    if "ckofakeserial" not in serial.protocol_handler_packages:
        serial.protocol_handler_packages.append("ckofakeserial")


class SerialTargetTests(unittest.TestCase):
    def test_serial_target_is_validated(self):
        target = _target({"connection": {"transport": "rtu_serial", "serial_port": "com3", "baudrate": 19200,
                                         "data_format": "8e1", "timeout_ms": 500}})
        self.assertEqual((target.host, target.baudrate, target.data_format, target.serial), ("COM3", 19200, "8E1", True))
        self.assertIn("RTU 19200 Baud 8E1", target.label)
        for bad in ({"serial_port": ""}, {"serial_port": "COM3; rm"}, {"serial_port": "COM3", "baudrate": 12345},
                    {"serial_port": "COM3", "data_format": "7X1"}):
            with self.subTest(bad=bad), self.assertRaises(InspectorError):
                _target({"connection": {"transport": "rtu_serial", **bad}})

    def test_serial_target_needs_no_ip_address(self):
        target = _target({"connection": {"transport": "rtu_serial", "serial_port": "/dev/ttyUSB0", "host": "8.8.8.8"}})
        self.assertEqual(target.host, "/dev/ttyUSB0")

    def test_probe_timeout_grows_for_slow_baudrates(self):
        self.assertEqual(rtu_probe_timeout_ms(9600), 145)
        self.assertGreater(rtu_probe_timeout_ms(1200), rtu_probe_timeout_ms(9600))
        self.assertEqual(rtu_probe_timeout_ms(115200), 120)

    def test_serial_ports_route(self):
        response = app_module.app.test_client().get("/api/serial-ports")
        self.assertEqual(response.status_code, 200)
        self.assertIn("ports", response.get_json())


@unittest.skipUnless(serial is not None and modbus_core.ModbusSerialClient, "pyserial nötig")
class FakeMeterTests(unittest.TestCase):
    def setUp(self):
        self.meter = METERS["bus1"] = FakeRtuMeter()
        self.path = "fakemeter://bus1"
        self.client = app_module.app.test_client()
        pattern = mock.patch.object(modbus_core, "SERIAL_PORT_PATTERN", re.compile(r"^fakemeter://\w+$"))
        pattern.start()
        self.addCleanup(pattern.stop)

    def tearDown(self):
        modbus_core.POOL.reset()

    def probe(self, baud, data_format, start=1, end=8):
        return self.client.post("/api/rtu-probe", json={
            "connection": {"serial_port": self.path, "baudrate": baud, "data_format": data_format},
            "start_id": start, "end_id": end, "function": 3, "address": 0})

    def test_search_finds_meter_only_with_matching_settings(self):
        wrong = self.probe(9600, "8N1").get_json()
        self.assertTrue(wrong["ok"])
        self.assertEqual(wrong["found"], [])
        parity = self.probe(19200, "8O1").get_json()
        self.assertEqual(parity["found"], [])
        right = self.probe(19200, "8E1").get_json()
        self.assertEqual([item["unit_id"] for item in right["found"]], [7])
        self.assertEqual(right["found"][0]["status"], "answer")
        self.assertGreaterEqual(self.meter.requests, 24)

    def test_read_poll_and_unit_scan_over_serial(self):
        connection = {"transport": "rtu_serial", "serial_port": self.path, "baudrate": 19200,
                      "data_format": "8E1", "timeout_ms": 300}
        connected = self.client.post("/api/connect", json={"connection": connection}).get_json()
        self.assertTrue(connected["ok"])
        self.assertIn("RTU 19200", connected["label"])
        read = self.client.post("/api/read", json={"connection": connection, "unit_id": 7, "function": 3,
                                                   "address": 0, "count": 4}).get_json()
        self.assertEqual(read["values"][:2], [2305, 1234])
        units = self.client.post("/api/unit-scan", json={"connection": connection, "start_id": 5, "end_id": 8}).get_json()
        self.assertEqual([item["unit_id"] for item in units["found"]], [7])
        polled = self.client.post("/api/poll", json={"connection": connection, "points": [
            {"id": "u", "name": "Spannung L1", "unit_id": 7, "function": 3, "address": 0, "data_type": "uint16",
             "order": "AB", "scale": 0.1, "offset": 0, "unit": "V"},
            {"id": "f", "name": "Frequenz", "unit_id": 7, "function": 3, "address": 2, "data_type": "float32",
             "order": "ABCD", "scale": 1, "offset": 0, "unit": "Hz"},
        ]}).get_json()
        values = {item["id"]: item for item in polled["points"]}
        self.assertAlmostEqual(values["u"]["value"], 230.5)
        self.assertEqual(values["u"]["hints"], [])
        self.assertEqual(values["f"]["value"], 50.0)
        status = self.client.get("/api/connections").get_json()["connections"]
        self.assertEqual(len(status), 1)  # alle Funktionen auf derselben Schnittstelle
        self.assertTrue(status[0]["open"])

    def test_timeouts_keep_the_port_open(self):
        self.probe(19200, "8E1", 1, 6)
        status = modbus_core.POOL.status()[0]
        self.assertTrue(status["open"])
        self.assertEqual(status["reconnects"], 0)
        self.assertEqual(self.meter.opens, 1)


class MissingPortTests(unittest.TestCase):
    def test_unavailable_port_gives_clear_message(self):
        response = app_module.app.test_client().post("/api/rtu-probe", json={
            "connection": {"serial_port": "/dev/ttyDOESNOTEXIST9", "baudrate": 9600, "data_format": "8N1"},
            "start_id": 1, "end_id": 2})
        self.assertEqual(response.status_code, 503)
        self.assertIn("USB-RS485-Adapter", response.get_json()["error"])


class MeterListTests(unittest.TestCase):
    def test_dpt_suggestions(self):
        self.assertEqual(knx_dpt({"unit": "W"})["dpt"], "14.056")
        self.assertEqual(knx_dpt({"unit": "kWh"})["dpt"], "13.013")
        self.assertEqual(knx_dpt({"unit": "V"})["dpt"], "14.027")
        self.assertEqual(knx_dpt({"unit": "A"})["dpt"], "14.019")
        self.assertEqual(knx_dpt({"unit": "Hz"})["dpt"], "14.033")
        self.assertEqual(knx_dpt({"name": "Leistungsfaktor L1", "unit": ""})["dpt"], "14.057")
        self.assertEqual(knx_dpt({"function": 1, "data_type": "bool"})["dpt"], "1.001")
        self.assertEqual(knx_dpt({"unit": "Schritte"})["dpt"], "14.xxx")

    def test_plausibility_hints(self):
        self.assertEqual(plausibility({"unit": "V", "name": "Spannung L1"}, 231.2), [])
        self.assertTrue(plausibility({"unit": "V", "name": "Spannung L1"}, 23.1))
        self.assertTrue(plausibility({"unit": "Hz", "name": "Frequenz"}, 5000))
        self.assertTrue(plausibility({"unit": "kWh", "name": "Energie"}, -3))
        self.assertTrue(plausibility({"unit": "", "name": "Leistungsfaktor"}, 950))
        self.assertTrue(plausibility({"unit": "W", "name": "Leistung Verbraucher"}, -1200))
        self.assertTrue(plausibility({"unit": "V", "name": "Spannung L1"}, 400))
        self.assertEqual(plausibility({"unit": "V", "name": "Spannung L1-L2"}, 400), [])
        self.assertEqual(plausibility({"unit": "W"}, None), [])

    def test_rows_and_csv(self):
        points = [{"id": "p", "name": "Leistung", "unit_id": 3, "function": 4, "address": 12, "data_type": "float32",
                   "order": "ABCD", "scale": 0.001, "offset": 0, "unit": "W"}]
        rows = build_rows(points, {"transport": "rtu_serial", "serial_port": "COM4", "baudrate": 9600, "data_format": "8E1"},
                          {"p": 1234.5})
        self.assertEqual(rows[0]["connection"], "RTU COM4 · 9600 Baud 8E1")
        self.assertEqual(rows[0]["dpt"], "14.056")
        text = build_csv(rows)
        self.assertTrue(text.startswith("﻿"))
        self.assertIn('"0,001"', text)
        self.assertIn('"1234,5"', text)
        with self.assertRaises(ValueError):
            build_rows([], {})

    def test_meter_list_route(self):
        response = app_module.app.test_client().post("/api/export/meter-list", json={
            "points": [{"id": "v", "name": "Spannung", "unit_id": 1, "function": 3, "address": 0, "data_type": "uint16",
                        "order": "AB", "scale": 0.1, "offset": 0, "unit": "V"}],
            "connection": {"transport": "tcp", "host": "10.80.80.20", "port": 502}, "values": {"v": 12.0}})
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["warnings"], 1)
        self.assertIn("Spannung", data["csv"])


class HomeAssistantSerialTests(unittest.TestCase):
    def test_serial_hub(self):
        text = build_yaml([{"name": "Leistung", "unit_id": 2, "function": 4, "address": 12, "data_type": "float32",
                            "order": "CDAB", "unit": "W"}],
                          {"transport": "rtu_serial", "serial_port": "COM4", "baudrate": 19200, "data_format": "8E1",
                           "timeout_ms": 1000})
        for line in ("type: serial", "method: rtu", 'port: "COM4"', "baudrate: 19200", "bytesize: 8", "parity: E",
                     "stopbits: 1", "device_address: 2", "swap: word"):
            self.assertIn(line, text)
        self.assertNotIn("host:", text)


if __name__ == "__main__":
    unittest.main()
