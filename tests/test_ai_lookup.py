import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
from google.genai import errors as gemini_errors

import ai_lookup
import app as app_module
import gemini_lookup
from ai_settings import AiSettingsStore
from modbus_core import InspectorError


class AiSettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = AiSettingsStore(Path(self.temporary_directory.name) / "settings.sqlite3")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_round_trip_and_clear(self):
        self.assertFalse(self.store.has_api_key())
        self.assertIsNone(self.store.get_api_key_masked())

        self.store.set_api_key("sk-ant-abcdefgh1234")
        self.assertTrue(self.store.has_api_key())
        self.assertEqual(self.store.get_api_key(), "sk-ant-abcdefgh1234")
        self.assertEqual(self.store.get_api_key_masked(), "…1234")

        self.store.set_api_key("")
        self.assertFalse(self.store.has_api_key())
        self.assertIsNone(self.store.get_api_key())


class AiLookupValidationTests(unittest.TestCase):
    def test_valid_payload_is_kept(self):
        raw = {
            "device_identified": True,
            "general_notes": "Testgerät gefunden.",
            "warnings": ["Adresse ungetestet."],
            "points": [
                {
                    "name": "Wirkleistung",
                    "quantity_kind": "power",
                    "function": 3,
                    "address": 100,
                    "data_type": "float32",
                    "order": "ABCD",
                    "scale": 1.0,
                    "unit": "kW",
                    "confidence": "mittel",
                    "source_url": "https://example.com/manual.pdf",
                }
            ],
        }
        result = ai_lookup._validate_suggestions_payload(raw)
        self.assertTrue(result["device_identified"])
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["points"][0]["name"], "Wirkleistung")
        self.assertEqual(result["points"][0]["order"], "ABCD")

    def test_invalid_entries_are_dropped_not_fatal(self):
        raw = {
            "device_identified": False,
            "general_notes": "",
            "warnings": [],
            "points": [
                {"name": "Kaputt", "quantity_kind": "power", "data_type": "not-a-type", "order": "X", "confidence": "hoch"},
                {"name": "Gut", "quantity_kind": "voltage", "data_type": "uint16", "order": "ZZ", "confidence": "unbekannt", "function": 99},
            ],
        }
        result = ai_lookup._validate_suggestions_payload(raw)
        self.assertEqual(len(result["points"]), 1)
        point = result["points"][0]
        self.assertEqual(point["name"], "Gut")
        self.assertEqual(point["order"], "AB")
        self.assertEqual(point["confidence"], "niedrig")
        self.assertIsNone(point["function"])

    def test_structurally_unusable_payload_raises(self):
        with self.assertRaises(InspectorError):
            ai_lookup._validate_suggestions_payload({"no_points_here": True})
        with self.assertRaises(InspectorError):
            ai_lookup._validate_suggestions_payload("not a dict")

    def test_oversized_points_list_is_capped(self):
        raw = {
            "device_identified": True,
            "general_notes": "",
            "warnings": [],
            "points": [
                {
                    "name": f"Punkt {i}",
                    "quantity_kind": "free",
                    "data_type": "uint16",
                    "order": "AB",
                    "confidence": "hoch",
                }
                for i in range(20)
            ],
        }
        result = ai_lookup._validate_suggestions_payload(raw)
        self.assertEqual(len(result["points"]), ai_lookup.MAX_SUGGESTIONS)


def _fake_message_with_text(payload: dict):
    text_block = SimpleNamespace(type="text", text=json.dumps(payload))
    return SimpleNamespace(content=[text_block])


class AiLookupClientTests(unittest.TestCase):
    @patch("ai_lookup.anthropic.Anthropic")
    def test_successful_lookup_returns_validated_payload(self, mock_anthropic_cls):
        payload = {
            "device_identified": True,
            "general_notes": "gefunden",
            "warnings": [],
            "points": [
                {
                    "name": "Spannung L1",
                    "quantity_kind": "voltage",
                    "function": 4,
                    "address": 10,
                    "data_type": "float32",
                    "order": "ABCD",
                    "scale": 0.1,
                    "unit": "V",
                    "confidence": "hoch",
                }
            ],
        }
        mock_client = mock_anthropic_cls.return_value
        mock_client.with_options.return_value.messages.create.return_value = _fake_message_with_text(payload)

        result = ai_lookup.lookup_device_points("Siemens", "PAC2200", "1.0", "fake-key")

        self.assertEqual(result["points"][0]["name"], "Spannung L1")
        mock_anthropic_cls.assert_called_once_with(api_key="fake-key")
        create_kwargs = mock_client.with_options.return_value.messages.create.call_args.kwargs
        self.assertEqual(create_kwargs["model"], ai_lookup.AI_MODEL)
        self.assertEqual(create_kwargs["tools"][0]["type"], "web_search_20260209")
        self.assertEqual(create_kwargs["output_config"]["format"]["type"], "json_schema")

    @patch("ai_lookup.anthropic.Anthropic")
    def test_rate_limit_error_is_mapped(self, mock_anthropic_cls):
        mock_client = mock_anthropic_cls.return_value
        fake_response = SimpleNamespace(request=None, status_code=429, headers={})
        mock_client.with_options.return_value.messages.create.side_effect = anthropic.RateLimitError(
            message="rate limited", response=fake_response, body=None
        )
        with self.assertRaises(InspectorError) as ctx:
            ai_lookup.lookup_device_points("Siemens", "PAC2200", "", "fake-key")
        self.assertEqual(ctx.exception.status_code, 503)

    @patch("ai_lookup.anthropic.Anthropic")
    def test_malformed_json_raises(self, mock_anthropic_cls):
        mock_client = mock_anthropic_cls.return_value
        text_block = SimpleNamespace(type="text", text="not json")
        mock_client.with_options.return_value.messages.create.return_value = SimpleNamespace(content=[text_block])
        with self.assertRaises(InspectorError) as ctx:
            ai_lookup.lookup_device_points("Siemens", "PAC2200", "", "fake-key")
        self.assertEqual(ctx.exception.status_code, 502)

    def test_quantity_lookup_requires_quantity_text(self):
        with self.assertRaises(InspectorError):
            ai_lookup.lookup_quantity("Siemens", "PAC2200", "", "   ", "fake-key")


class AiRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        app_module._ai_settings_store = AiSettingsStore(Path(self.temporary_directory.name) / "settings.sqlite3")
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module._ai_settings_store = None
        self.temporary_directory.cleanup()

    def test_settings_roundtrip_never_leaks_full_key(self):
        response = self.client.get("/api/ai-settings")
        expected_empty = {
            "ok": True,
            "provider": "anthropic",
            "providers": {
                "anthropic": {"has_api_key": False, "api_key_masked": None},
                "gemini": {"has_api_key": False, "api_key_masked": None},
            },
        }
        self.assertEqual(response.get_json(), expected_empty)

        saved = self.client.post("/api/ai-settings", json={"anthropic_api_key": "sk-ant-abcdefgh1234"})
        data = saved.get_json()
        self.assertTrue(data["providers"]["anthropic"]["has_api_key"])
        self.assertEqual(data["providers"]["anthropic"]["api_key_masked"], "…1234")
        self.assertNotIn("sk-ant-abcdefgh1234", json.dumps(data))

    def test_gemini_key_and_provider_switch_roundtrip(self):
        saved = self.client.post(
            "/api/ai-settings",
            json={"gemini_api_key": "gm-abcdefgh5678", "provider": "gemini"},
        )
        data = saved.get_json()
        self.assertEqual(data["provider"], "gemini")
        self.assertTrue(data["providers"]["gemini"]["has_api_key"])
        self.assertEqual(data["providers"]["gemini"]["api_key_masked"], "…5678")
        self.assertNotIn("gm-abcdefgh5678", json.dumps(data))

    def test_invalid_provider_returns_400(self):
        response = self.client.post("/api/ai-settings", json={"provider": "does-not-exist"})
        self.assertEqual(response.status_code, 400)

    def test_lookup_without_key_returns_400(self):
        response = self.client.post(
            "/api/ai/lookup", json={"manufacturer": "Siemens", "model": "PAC2200"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("KI-Einstellungen", response.get_json()["error"])

    def test_lookup_without_manufacturer_or_model_returns_400(self):
        self.client.post("/api/ai-settings", json={"anthropic_api_key": "fake-key"})
        response = self.client.post("/api/ai/lookup", json={})
        self.assertEqual(response.status_code, 400)

    @patch("app.lookup_device_points")
    def test_successful_lookup_is_passed_through(self, mock_lookup):
        self.client.post("/api/ai-settings", json={"anthropic_api_key": "fake-key"})
        mock_lookup.return_value = {
            "device_identified": True,
            "general_notes": "",
            "warnings": [],
            "points": [],
        }
        response = self.client.post(
            "/api/ai/lookup", json={"manufacturer": "Siemens", "model": "PAC2200"}
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["provider"], "anthropic")
        mock_lookup.assert_called_once_with("Siemens", "PAC2200", "", "fake-key")

    @patch("app.gemini_lookup_device_points")
    def test_gemini_provider_is_used_when_selected(self, mock_lookup):
        self.client.post(
            "/api/ai-settings",
            json={"gemini_api_key": "fake-gemini-key", "provider": "gemini"},
        )
        mock_lookup.return_value = {
            "device_identified": True,
            "general_notes": "",
            "warnings": [],
            "points": [],
        }
        response = self.client.post(
            "/api/ai/lookup", json={"manufacturer": "Siemens", "model": "PAC2200"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["provider"], "gemini")
        mock_lookup.assert_called_once_with("Siemens", "PAC2200", "", "fake-gemini-key")

    def test_gemini_provider_without_key_returns_400(self):
        self.client.post("/api/ai-settings", json={"provider": "gemini"})
        response = self.client.post(
            "/api/ai/lookup", json={"manufacturer": "Siemens", "model": "PAC2200"}
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Google Gemini", response.get_json()["error"])


class GeminiLookupValidationTests(unittest.TestCase):
    def test_valid_payload_is_kept(self):
        raw = {
            "device_identified": True,
            "general_notes": "Testgerät gefunden.",
            "warnings": [],
            "points": [
                {
                    "name": "Netzfrequenz",
                    "quantity_kind": "frequency",
                    "function": 4,
                    "address": 50,
                    "data_type": "float32",
                    "order": "ABCD",
                    "scale": 1.0,
                    "unit": "Hz",
                    "confidence": "mittel",
                }
            ],
        }
        result = gemini_lookup._validate_suggestions_payload(raw)
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["points"][0]["name"], "Netzfrequenz")


class GeminiLookupClientTests(unittest.TestCase):
    @patch("gemini_lookup.genai.Client")
    def test_successful_lookup_runs_two_calls_and_returns_validated_payload(self, mock_client_cls):
        payload = {
            "device_identified": True,
            "general_notes": "gefunden",
            "warnings": [],
            "points": [
                {
                    "name": "Wirkleistung",
                    "quantity_kind": "power",
                    "function": 3,
                    "address": 200,
                    "data_type": "int32",
                    "order": "ABCD",
                    "scale": 0.1,
                    "unit": "kW",
                    "confidence": "hoch",
                }
            ],
        }
        mock_client = mock_client_cls.return_value
        research_response = SimpleNamespace(text="Ich habe die Dokumentation gefunden.")
        extraction_response = SimpleNamespace(text=json.dumps(payload))
        mock_client.models.generate_content.side_effect = [research_response, extraction_response]

        result = gemini_lookup.lookup_device_points("Siemens", "PAC2200", "1.0", "fake-key")

        self.assertEqual(result["points"][0]["name"], "Wirkleistung")
        mock_client_cls.assert_called_once()
        self.assertEqual(mock_client.models.generate_content.call_count, 2)

    @patch("gemini_lookup.genai.Client")
    def test_api_error_is_mapped(self, mock_client_cls):
        mock_client = mock_client_cls.return_value
        mock_client.models.generate_content.side_effect = gemini_errors.APIError(
            429, {"error": {"message": "rate limited"}}, None
        )
        with self.assertRaises(InspectorError) as ctx:
            gemini_lookup.lookup_device_points("Siemens", "PAC2200", "", "fake-key")
        self.assertEqual(ctx.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
