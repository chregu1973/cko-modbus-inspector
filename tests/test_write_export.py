import unittest
from unittest.mock import patch

import app as app_module
import modbus_core
from ha_export import build_yaml
from modbus_core import InspectorError, decode_registers, decode_selected, encode_value


class EncodeTests(unittest.TestCase):
    def test_encode_is_inverse_of_decode_for_all_orders(self):
        cases = [("uint16", 1234, "AB"), ("int16", -5, "BA"), ("float16", 1.5, "AB"),
                 ("int32", -123456, "CDAB"), ("float32", 21.5, "BADC"), ("uint64", 2**40 + 7, "GHEFCDAB"),
                 ("float64", -0.125, "HGFEDCBA")]
        for data_type, value, order in cases:
            with self.subTest(data_type=data_type, order=order):
                registers = encode_value(value, data_type, order)
                self.assertEqual(decode_selected(registers, data_type, order), value)

    def test_scale_and_offset_are_reversed(self):
        self.assertEqual(encode_value(23.4, "int16", "AB", scale=0.1), [234])
        self.assertEqual(encode_value(20, "uint16", "AB", scale=0.5, offset=-40), [120])

    def test_out_of_range_and_bad_input_are_rejected(self):
        with self.assertRaises(InspectorError):
            encode_value(70000, "uint16")
        with self.assertRaises(InspectorError):
            encode_value("abc", "int32")

    def test_string_encoding_and_decoding(self):
        registers = encode_value("SDM630", "string", "AB", length=4)
        self.assertEqual(registers, [0x5344, 0x4D36, 0x3330, 0x0000])
        self.assertEqual(decode_selected(registers, "string", "AB"), "SDM630")
        self.assertEqual(decode_selected(encode_value("AB", "string", "BA", length=1), "string", "BA"), "AB")

    def test_decoder_shows_float16_and_text(self):
        result = decode_registers(encode_value("Fronius", "string", "AB", length=4))
        labels = [group["label"] for group in result["groups"]]
        self.assertIn("Text", labels)
        self.assertIn("Float16", [row["type"] for row in result["groups"][0]["rows"]])
        text = next(group for group in result["groups"] if group["label"] == "Text")
        self.assertEqual(text["rows"][0]["value"], "Fronius")


class Response:
    def __init__(self, registers=None, bits=None, error=False, code=None):
        self.registers, self.bits, self._error, self.exception_code = registers or [], bits or [], error, code

    def isError(self):
        return self._error


class FakeWriteClient:
    def __init__(self):
        self.memory = {}
        self.calls = []

    def connect(self):
        return True

    def close(self):
        pass

    def write_register(self, address, value, *, device_id=1):
        self.calls.append(("FC06", address, value))
        self.memory[address] = value
        return Response()

    def write_registers(self, address, values, *, device_id=1):
        self.calls.append(("FC16", address, list(values)))
        for index, value in enumerate(values):
            self.memory[address + index] = value
        return Response()

    def write_coil(self, address, value, *, device_id=1):
        self.calls.append(("FC05", address, value))
        self.memory[("coil", address)] = value
        return Response()

    def read_holding_registers(self, address, *, count=1, device_id=1):
        return Response(registers=[self.memory.get(address + i, 0) for i in range(count)])

    def read_coils(self, address, *, count=1, device_id=1):
        return Response(bits=[self.memory.get(("coil", address), False)])


class WriteTests(unittest.TestCase):
    def setUp(self):
        modbus_core.set_write_mode(False)
        self.client = app_module.app.test_client()
        self.fake = FakeWriteClient()
        self.base = {"connection": {"host": "127.0.0.1", "port": 502}, "unit_id": 1, "confirmed": True}

    def tearDown(self):
        modbus_core.set_write_mode(False)

    def post(self, body):
        with patch("modbus_core._client", return_value=self.fake):
            return self.client.post("/api/write", json={**self.base, **body})

    def test_write_is_locked_until_enabled(self):
        response = self.post({"function": 3, "address": 10, "data_type": "uint16", "value": 5})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.fake.calls, [])

    def test_write_requires_confirmation(self):
        modbus_core.set_write_mode(True)
        response = self.post({"function": 3, "address": 10, "data_type": "uint16", "value": 5, "confirmed": False})
        self.assertEqual(response.status_code, 428)

    def test_single_register_uses_fc06_and_is_verified(self):
        modbus_core.set_write_mode(True)
        data = self.post({"function": 3, "address": 10, "data_type": "int16", "order": "AB", "value": 21.5, "scale": 0.1}).get_json()
        self.assertEqual(self.fake.calls, [("FC06", 10, 215)])
        self.assertTrue(data["verified"])
        self.assertEqual(data["readback"], [215])

    def test_multi_register_uses_fc16(self):
        modbus_core.set_write_mode(True)
        data = self.post({"function": 3, "address": 100, "data_type": "float32", "order": "CDAB", "value": 12.75}).get_json()
        self.assertEqual(self.fake.calls[0][0], "FC16")
        self.assertTrue(data["verified"])

    def test_coil_uses_fc05(self):
        modbus_core.set_write_mode(True)
        data = self.post({"function": 1, "address": 3, "value": "ein"}).get_json()
        self.assertEqual(self.fake.calls, [("FC05", 3, True)])
        self.assertTrue(data["verified"])

    def test_input_registers_are_read_only(self):
        modbus_core.set_write_mode(True)
        response = self.post({"function": 4, "address": 0, "data_type": "uint16", "value": 1})
        self.assertEqual(response.status_code, 400)
        self.assertIn("nur lesbar", response.get_json()["error"])

    def test_write_mode_expires_and_health_reflects_it(self):
        self.assertTrue(self.client.get("/api/health").get_json()["read_only"])
        state = self.client.post("/api/write-mode", json={"enabled": True}).get_json()
        self.assertTrue(state["enabled"])
        self.assertGreater(state["remaining_s"], 1700)
        self.assertFalse(self.client.get("/api/health").get_json()["read_only"])
        with patch("modbus_core.time.time", return_value=modbus_core.time.time() + 31 * 60):
            self.assertFalse(modbus_core.write_mode_status()["enabled"])


class HomeAssistantExportTests(unittest.TestCase):
    points = [
        {"name": "Wirkleistung gesamt", "unit_id": 1, "function": 4, "address": 52, "data_type": "float32", "order": "ABCD", "scale": 1, "offset": 0, "unit": "W"},
        {"name": "Temperatur", "unit_id": 3, "function": 3, "address": 30775, "data_type": "int32", "order": "CDAB", "scale": 0.1, "offset": 0, "unit": "°C"},
        {"name": "Seriennummer", "unit_id": 3, "function": 3, "address": 40052, "data_type": "string", "order": "AB", "length": 16},
        {"name": "Pumpe läuft", "unit_id": 3, "function": 1, "address": 5, "data_type": "bool"},
        {"name": "Temperatur", "unit_id": 3, "function": 3, "address": 30777, "data_type": "uint16", "order": "BA", "scale": 1, "offset": -40, "unit": "°C"},
    ]

    def test_yaml_contains_hub_sensors_and_binary_sensors(self):
        text = build_yaml(self.points, {"host": "10.80.80.20", "port": 502, "transport": "tcp", "timeout_ms": 800, "wait_ms": 50}, "Zähler Technik")
        self.assertIn('  - name: "Zähler Technik"\n    type: tcp\n    host: "10.80.80.20"\n    port: 502\n    timeout: 1', text)
        self.assertIn("message_wait_milliseconds: 50", text)
        self.assertIn("        input_type: input\n        data_type: float32\n        precision: 2\n        unit_of_measurement: \"W\"", text)
        self.assertIn("        device_address: 3\n        address: 30775\n        input_type: holding\n        data_type: int32\n        swap: word\n        scale: 0.1\n        precision: 1", text)
        self.assertIn("        data_type: string\n        count: 16", text)
        self.assertIn("    binary_sensors:\n      - name: \"Pumpe läuft\"", text)
        self.assertIn("        input_type: coil", text)
        self.assertIn("swap: byte", text)
        self.assertIn("offset: -40", text)
        self.assertIn('unique_id: "zahler_technik_temperatur_2"', text)

    def test_rtu_over_tcp_and_api(self):
        response = app_module.app.test_client().post("/api/export/home-assistant", json={
            "points": self.points[:1], "connection": {"host": "10.80.80.21", "transport": "rtu_tcp"}, "name": ""})
        self.assertEqual(response.status_code, 200)
        self.assertIn("type: rtuovertcp", response.get_json()["yaml"])
        self.assertEqual(app_module.app.test_client().post("/api/export/home-assistant", json={"points": []}).status_code, 400)

    def test_yaml_is_valid(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML nicht installiert")
        data = yaml.safe_load(build_yaml(self.points, {"host": "10.80.80.20"}, "Test"))
        hub = data["modbus"][0]
        self.assertEqual(len(hub["sensors"]), 4)
        self.assertEqual(hub["binary_sensors"][0]["input_type"], "coil")
