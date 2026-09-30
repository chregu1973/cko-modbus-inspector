import unittest
from unittest.mock import patch

from modbus_core import (
    InspectorError,
    ModbusException,
    decode_registers,
    decode_selected,
    match_register_values,
    poll_points,
    scan_registers,
    scan_network,
    scan_unit_ids,
)


class DecoderTests(unittest.TestCase):
    def test_float32_big_endian(self):
        self.assertEqual(decode_selected([0x41AC, 0x0000], "float32", "ABCD"), 21.5)

    def test_word_swap(self):
        self.assertEqual(decode_selected([0x0000, 0x41AC], "float32", "CDAB"), 21.5)

    def test_signed_16(self):
        self.assertEqual(decode_selected([0xFFFF], "int16", "AB"), -1)

    def test_decoder_contains_expected_value(self):
        decoded = decode_registers([0x41AC, 0x0000, 0, 0])
        values = {(row["data_type"], row["order"]): row["value"] for group in decoded["groups"] for row in group["rows"]}
        self.assertEqual(values[("float32", "ABCD")], 21.5)

    def test_wrong_word_count(self):
        with self.assertRaises(InspectorError):
            decode_selected([1], "float32", "ABCD")

    def test_target_value_search_finds_offset_and_scale(self):
        result = match_register_values(
            {
                "registers": [0, 0, 0, 0x731F, 0, 0],
                "start_address": 20480,
                "expected_value": 294.71,
                "tolerance_percent": 1,
                "type_mode": "auto",
            }
        )
        best = result["matches"][0]
        self.assertEqual(best["address"], 20482)
        self.assertEqual(best["data_type"], "uint32")
        self.assertEqual(best["order"], "ABCD")
        self.assertEqual(best["factor"], 0.01)
        self.assertAlmostEqual(best["value"], 294.71)
        self.assertTrue(best["within_tolerance"])

    def test_target_value_search_rejects_empty_registers(self):
        with self.assertRaises(InspectorError):
            match_register_values({"registers": [], "expected_value": 10})

    def test_power_search_prefers_plausible_signed_32_bit_register(self):
        # 23316/23317 encode SINT32 -3'969'172 => -39.69172 with factor 0.00001.
        # 23318 deliberately contains a numerically closer but coincidental
        # byte-swapped SINT16 value (-4'097 => -40.97 with factor 0.01).
        result = match_register_values(
            {
                "registers": [0xFFC3, 0x6F6C, 0xFFEF, 0],
                "start_address": 23316,
                "expected_value": -41,
                "tolerance_percent": 10,
                "type_mode": "auto",
                "quantity_kind": "power",
                "limit": 5,
            }
        )
        best = result["recommendation"]
        self.assertEqual(best["address"], 23316)
        self.assertEqual(best["data_type"], "int32")
        self.assertEqual(best["visu_type"], "SINT32")
        self.assertEqual(best["order"], "ABCD")
        self.assertEqual(best["factor"], 0.00001)
        self.assertAlmostEqual(best["value"], -39.69172)
        self.assertEqual(best["confidence_label"], "hoch")

    def test_power_search_recognizes_an_unknown_flow_direction(self):
        # Field display supplied only the magnitude (+59 kW), while the meter
        # uses a negative sign for the current energy-flow direction.
        result = match_register_values(
            {
                "registers": [0xFFFF, 0xFFFF, 0xFFA4, 0xF8C6, 0xFFE1, 0xA72F],
                "start_address": 23314,
                "expected_value": 59,
                "tolerance_percent": 15,
                "type_mode": "auto",
                "quantity_kind": "power",
                "limit": 5,
            }
        )
        best = result["recommendation"]
        self.assertEqual(best["address"], 23316)
        self.assertEqual(best["data_type"], "int32")
        self.assertEqual(best["order"], "ABCD")
        self.assertEqual(best["factor"], 0.00001)
        self.assertAlmostEqual(best["value"], -59.65626)
        self.assertTrue(best["polarity_mismatch"])
        self.assertEqual(best["confidence_label"], "hoch")
        self.assertIn("Energieflussrichtung", best["reasons"][0])

    def test_target_value_search_groups_equivalent_signed_unsigned_values(self):
        result = match_register_values(
            {
                "registers": [0, 0x731F],
                "start_address": 20482,
                "expected_value": 294.71,
                "tolerance_percent": 1,
                "type_mode": "32",
                "quantity_kind": "energy",
            }
        )
        best = result["matches"][0]
        self.assertEqual(best["data_type"], "uint32")
        self.assertIn("Int32 · ABCD", best["equivalent_interpretations"])
        self.assertLess(result["unique_candidate_count"], result["candidate_count"])

    def test_target_value_search_accepts_a_custom_factor(self):
        result = match_register_values(
            {
                "registers": [4000],
                "expected_value": 1,
                "tolerance_percent": 0,
                "type_mode": "16",
                "quantity_kind": "free",
                "custom_factor": 0.00025,
            }
        )
        self.assertEqual(result["matches"][0]["factor"], 0.00025)
        self.assertEqual(result["matches"][0]["value"], 1)

    def test_equal_16_and_32_bit_value_prefers_complete_32_bit_candidate(self):
        result = match_register_values(
            {
                "registers": [0, 68, 0, 103, 0, 215],
                "start_address": 30845,
                "expected_value": 68,
                "tolerance_percent": 10,
                "type_mode": "auto",
                "quantity_kind": "percent",
                "limit": 5,
            }
        )
        best = result["recommendation"]
        self.assertEqual((best["address"], best["data_type"], best["order"]), (30845, "uint32", "ABCD"))
        self.assertEqual(best["factor"], 1)
        self.assertTrue(best["width_ambiguous"])
        self.assertEqual(best["confidence_label"], "mittel")
        self.assertGreaterEqual(result["ambiguous_candidates"], 2)
        self.assertTrue(any(item["address"] == 30846 and item["register_count"] == 1 for item in result["matches"]))


class SafetyTests(unittest.TestCase):
    def test_rejects_large_network(self):
        with self.assertRaises(InspectorError):
            scan_network({"cidr": "192.168.0.0/16", "port": 502, "timeout_ms": 50})

    def test_rejects_public_network(self):
        with self.assertRaises(InspectorError):
            scan_network({"cidr": "8.8.8.0/24", "port": 502, "timeout_ms": 50})


class UnitScanTests(unittest.TestCase):
    class TimeoutClient:
        def connect(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, *, count=1, device_id=1):
            raise ModbusException("No response received")

    class ExceptionResponse:
        exception_code = 2

        def isError(self):
            return True

    class ExceptionClient(TimeoutClient):
        def read_holding_registers(self, address, *, count=1, device_id=1):
            return UnitScanTests.ExceptionResponse()

    @patch("modbus_core._client", return_value=TimeoutClient())
    def test_timeout_is_visible_in_attempts(self, _client):
        result = scan_unit_ids(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "start_id": 1,
                "end_id": 1,
                "function": 3,
                "address": 20482,
            }
        )
        self.assertEqual(result["found"], [])
        self.assertEqual(result["attempts"][0]["status"], "timeout")
        self.assertIn("keine gültige Modbus-Antwort", result["warning"])

    @patch("modbus_core._client", return_value=ExceptionClient())
    def test_protocol_exception_counts_as_unit_response(self, _client):
        result = scan_unit_ids(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "start_id": 1,
                "end_id": 1,
                "function": 3,
                "address": 0,
            }
        )
        self.assertEqual(result["found"][0]["status"], "exception")


class RegisterScanTests(unittest.TestCase):
    class ValueResponse:
        def __init__(self, value):
            self.registers = [value]

        def isError(self):
            return False

    class IllegalAddressResponse:
        exception_code = 2

        def isError(self):
            return True

    class SparseClient:
        def connect(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, *, count=1, device_id=1):
            if address in (2, 3):
                return RegisterScanTests.ValueResponse(100 + address)
            return RegisterScanTests.IllegalAddressResponse()

        def read_input_registers(self, address, *, count=1, device_id=1):
            if address == 4:
                return RegisterScanTests.ValueResponse(204)
            return RegisterScanTests.IllegalAddressResponse()

    @patch("modbus_core._client", return_value=SparseClient())
    def test_finds_sparse_fc03_and_fc04_registers(self, _client):
        result = scan_registers(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "unit_id": 1,
                "function": 0,
                "start_address": 0,
                "end_address": 4,
                "delay_ms": 0,
            }
        )
        found = {(item["function"], item["address"], item["value"]) for item in result["found"]}
        self.assertEqual(found, {(3, 2, 102), (3, 3, 103), (4, 4, 204)})
        self.assertEqual(result["checked"], 10)
        self.assertEqual(result["unsupported"], 7)

    class MultiRegisterOnlyClient:
        def connect(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, *, count=1, device_id=1):
            values = {
                30845: [0x0000, 0x004B],
                30849: [0x0000, 0x00D7],
            }
            if count == 2 and address in values:
                response = RegisterScanTests.ValueResponse(0)
                response.registers = values[address]
                return response
            return RegisterScanTests.IllegalAddressResponse()

    @patch("modbus_core._client", return_value=MultiRegisterOnlyClient())
    def test_retries_illegal_single_register_as_32_bit_block(self, _client):
        result = scan_registers(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "unit_id": 10,
                "function": 3,
                "start_address": 30844,
                "end_address": 30850,
                "delay_ms": 0,
            }
        )
        found = {item["address"]: item for item in result["found"]}
        self.assertEqual(found[30845]["read_count"], 2)
        self.assertEqual(found[30845]["block_start"], 30845)
        self.assertEqual(found[30846]["value"], 75)
        self.assertEqual(found[30849]["read_count"], 2)
        self.assertEqual(found[30850]["value"], 215)
        self.assertEqual(result["checked"], 7)
        self.assertEqual(result["block_hits"], 2)
        self.assertIn("Mehrregister-Block", result["warning"])

    class GroupedBlockOnlyClient:
        def __init__(self):
            self.calls = 0

        def connect(self):
            return True

        def close(self):
            pass

        def read_holding_registers(self, address, *, count=1, device_id=1):
            self.calls += 1
            if address == 30845 and count == 6:
                response = RegisterScanTests.ValueResponse(0)
                response.registers = [0, 68, 0, 103, 0, 215]
                return response
            return RegisterScanTests.IllegalAddressResponse()

    @patch("modbus_core._client", return_value=GroupedBlockOnlyClient())
    def test_finds_device_that_only_allows_a_six_register_block(self, _client):
        result = scan_registers(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "unit_id": 10,
                "function": 3,
                "start_address": 30844,
                "end_address": 30850,
                "delay_ms": 0,
            }
        )
        found = {item["address"]: item for item in result["found"]}
        self.assertEqual(set(found), set(range(30845, 30851)))
        self.assertEqual(found[30845]["read_count"], 6)
        self.assertEqual(found[30850]["block_start"], 30845)
        self.assertEqual(result["blocks"], [{"function": 3, "start": 30845, "count": 6}])
        self.assertEqual(result["block_hits"], 1)

    @patch("modbus_core._client", return_value=GroupedBlockOnlyClient())
    def test_monitor_reuses_the_required_block_and_extracts_the_point(self, _client):
        result = poll_points(
            {
                "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                "points": [
                    {
                        "id": "charge",
                        "unit_id": 10,
                        "function": 3,
                        "address": 30845,
                        "data_type": "uint32",
                        "order": "ABCD",
                        "scale": 1,
                        "offset": 0,
                        "read_start": 30845,
                        "read_count": 6,
                        "value_offset": 0,
                    },
                    {
                        "id": "temperature",
                        "unit_id": 10,
                        "function": 3,
                        "address": 30849,
                        "data_type": "int32",
                        "order": "ABCD",
                        "scale": 0.1,
                        "offset": 0,
                        "read_start": 30845,
                        "read_count": 6,
                        "value_offset": 4,
                    },
                ],
            }
        )
        self.assertEqual(_client.return_value.calls, 1)
        self.assertEqual(result["points"][0]["value"], 68)
        point = result["points"][1]
        self.assertTrue(point["ok"])
        self.assertEqual(point["raw"], [0, 215])
        self.assertEqual(point["value"], 21.5)
        self.assertEqual((point["read_start"], point["read_count"], point["value_offset"]), (30845, 6, 4))

    def test_limits_register_range(self):
        with self.assertRaises(InspectorError):
            scan_registers(
                {
                    "connection": {"host": "127.0.0.1", "port": 502, "timeout_ms": 100},
                    "start_address": 0,
                    "end_address": 512,
                }
            )


if __name__ == "__main__":
    unittest.main()
