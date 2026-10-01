import io
import json
import unittest
from unittest.mock import patch

import app as app_module


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _tools(version):
    payload = [{"id": "knx-inspector", "version": "99.0.0"}, {"id": "modbus-inspector", "version": version}]
    return lambda request, timeout: _Response(json.dumps(payload).encode())


class UpdateCheckTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_newer_version_is_reported(self):
        with patch("app.urllib.request.urlopen", _tools("9.9.9")):
            data = self.client.get("/api/update-check").get_json()
        self.assertTrue(data["update_available"])
        self.assertEqual(data["latest"], "9.9.9")
        self.assertTrue(data["download_url"].endswith("/tools/modbus-inspector/#download"))

    def test_same_or_older_version_is_quiet(self):
        with patch("app.urllib.request.urlopen", _tools(app_module.APP_VERSION)):
            self.assertFalse(self.client.get("/api/update-check").get_json()["update_available"])
        with patch("app.urllib.request.urlopen", _tools("0.1.0")):
            self.assertFalse(self.client.get("/api/update-check").get_json()["update_available"])

    def test_offline_does_not_fail(self):
        def offline(request, timeout):
            raise OSError("offline")

        with patch("app.urllib.request.urlopen", offline):
            data = self.client.get("/api/update-check").get_json()
        self.assertFalse(data["checked"])
        self.assertFalse(data["update_available"])

    def test_versions_compare_numerically(self):
        self.assertGreater(app_module._version_tuple("0.10.0"), app_module._version_tuple("0.9.9"))
        self.assertEqual(app_module._version_tuple("0.1.14-mvp"), (0, 1, 14))
