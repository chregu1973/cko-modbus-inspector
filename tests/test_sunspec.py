import struct
import unittest
from unittest.mock import patch

import app as app_module
import sunspec


def _string(text, size):
    data = text.encode().ljust(size * 2, b"\x00")
    return [int.from_bytes(data[i:i + 2], "big") for i in range(0, size * 2, 2)]


def _build_device(base=40000):
    """Simuliertes SunSpec-Gerät: Modell 1 (Typenschild), 103 (Wechselrichter), 160 (2 MPP-Tracker), Ende."""
    regs = {}
    model1 = [1, 66] + _string("Fronius", 16) + _string("Symo 10.0-3-M", 16) + _string("", 8) + _string("1.28.7", 8) + _string("34112233", 16) + [1, 0x8000]
    m103 = [0] * 52
    m103[0], m103[1] = 103, 50
    names = [p["name"] for p in sunspec.models()["103"]["points"]]
    def put(name, value):
        offset = 0
        for point in sunspec.models()["103"]["points"]:
            if point["name"] == name:
                m103[offset] = value & 0xFFFF
                return
            offset += point.get("size", 1)
    for name in names[2:]:
        put(name, 0xFFFF)
    put("A", 1234); put("A_SF", -2)           # 12,34 A
    put("PhVphA", 2301); put("V_SF", -1)       # 230,1 V
    put("W", 7500); put("W_SF", 0)             # 7500 W
    put("PPVphAB", 0xFFFF)                     # nicht implementiert
    put("Hz", 5001); put("Hz_SF", -2)
    put("St", 4)                               # Enum ohne Skalierung
    m160_points = sunspec.models()["160"]["points"]
    fixed = sum(p.get("size", 1) for p in m160_points)
    module = sum(p.get("size", 1) for p in sunspec.models()["160"]["groups"][0]["points"])
    m160 = [160, fixed - 2 + 2 * module] + [0] * (fixed - 2 + 2 * module)
    regs_list = [0x5375, 0x6E53] + model1 + m103 + m160 + [0xFFFF, 0]
    for index, value in enumerate(regs_list):
        regs[base + index] = value
    return regs


class Response:
    def __init__(self, registers=None, error=False):
        self.registers, self._error = registers or [], error

    def isError(self):
        return self._error


def reader(regs):
    def read(address, count):
        if address not in regs:
            return Response(error=True)
        return Response([regs.get(address + i, 0) for i in range(count)])
    return read


class SunSpecTests(unittest.TestCase):
    def test_finds_models_scales_values_and_marks_unimplemented(self):
        result = sunspec.scan(reader(_build_device()))
        self.assertTrue(result["found"])
        self.assertEqual(result["base"], 40000)
        self.assertEqual([model["id"] for model in result["models"]], [1, 103, 160])
        self.assertEqual(result["device"]["Mn"], "Fronius")
        self.assertEqual(result["device"]["Md"], "Symo 10.0-3-M")
        self.assertEqual(result["device"]["SN"], "34112233")
        inverter = {p["name"]: p for p in result["models"][1]["points"]}
        self.assertEqual(inverter["A"]["value"], 12.34)
        self.assertEqual(inverter["A"]["scale"], 0.01)
        self.assertEqual(inverter["A"]["scale_factor_address"], inverter["A_SF"]["address"])
        self.assertEqual(inverter["PhVphA"]["value"], 230.1)
        self.assertEqual(inverter["W"]["value"], 7500)
        self.assertFalse(inverter["PPVphAB"]["implemented"])
        self.assertEqual(inverter["St"]["value"], 4)
        self.assertEqual(inverter["A"]["address"], 40000 + 2 + 68 + 2)
        mppt = [p["name"] for p in result["models"][2]["points"]]
        self.assertTrue(any(name.startswith("module2.") for name in mppt))
        self.assertEqual(inverter["A"]["label"], "Strom gesamt")
        self.assertEqual(inverter["PhVphA"]["label"], "Spannung L1-N")
        module_labels = [p["label"] for p in result["models"][2]["points"] if p["name"] == "module2.DCA"]
        self.assertEqual(module_labels, ["DC-Strom (Modul 2)"])

    def test_base_address_50000_and_missing_device(self):
        self.assertEqual(sunspec.scan(reader(_build_device(base=50000)))["base"], 50000)
        missing = sunspec.scan(reader({}))
        self.assertFalse(missing["found"])
        self.assertIn("SunSpec", missing["hint"])

    def test_float_and_string_decoding(self):
        float_regs = list(struct.unpack(">HH", struct.pack(">f", 49.95)))
        self.assertAlmostEqual(sunspec.decode_point({"type": "float32"}, float_regs), 49.95, places=4)
        self.assertIsNone(sunspec.decode_point({"type": "acc32"}, [0, 0]))
        self.assertEqual(sunspec.decode_point({"type": "int16"}, [0xFFFE]), -2)

    def test_api_uses_shared_connection(self):
        regs = _build_device()

        class Client:
            def connect(self):
                return True

            def close(self):
                pass

            def read_holding_registers(self, address, *, count=1, device_id=1):
                return reader(regs)(address, count)

        with patch("modbus_core._client", return_value=Client()):
            data = app_module.app.test_client().post("/api/sunspec-scan", json={"connection": {"host": "127.0.0.1"}, "unit_id": 1}).get_json()
        self.assertTrue(data["found"])
        self.assertEqual(data["device"]["Mn"], "Fronius")
