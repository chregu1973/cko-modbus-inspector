import tempfile
import unittest
from pathlib import Path

import app as app_module
from profile_store import ProfileStore


def sample_profile(name="PAC2200", project="MFH Musterstrasse"):
    return {
        "schema": "hbtec-modbus-profile",
        "schema_version": 1,
        "app_version": "0.1.9-mvp",
        "profile": {
            "name": name,
            "project": project,
            "manufacturer": "Siemens",
            "model": "7KM PAC2200",
            "firmware": "1.2.3",
            "notes": "Testprofil",
        },
        "connection": {
            "host": "192.168.1.100",
            "port": 502,
            "timeout_ms": 800,
            "transport": "tcp",
        },
        "points": [
            {
                "id": "energy-import",
                "name": "Energie Bezug",
                "unit_id": 1,
                "function": 3,
                "address": 20482,
                "data_type": "uint32",
                "order": "ABCD",
                "scale": 0.01,
                "offset": 0,
                "unit": "kWh",
            }
        ],
    }


class ProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = ProfileStore(Path(self.temporary_directory.name) / "profiles.sqlite3")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_save_search_update_and_delete(self):
        saved = self.store.save(sample_profile())
        self.assertEqual(saved["name"], "PAC2200")
        self.assertEqual(saved["point_count"], 1)
        self.assertEqual(self.store.list("Siemens")[0]["id"], saved["id"])

        updated_payload = sample_profile("PAC2200 Hauptverteilung", "Werk Luzern")
        updated = self.store.save(updated_payload, saved["id"])
        self.assertEqual(updated["id"], saved["id"])
        loaded = self.store.get(saved["id"])
        self.assertEqual(loaded["payload"]["profile"]["project"], "Werk Luzern")
        self.assertTrue(self.store.delete(saved["id"]))
        self.assertFalse(self.store.delete(saved["id"]))

    def test_backup_can_be_restored(self):
        original = self.store.save(sample_profile())
        backup = self.store.export_backup()
        second_store = ProfileStore(Path(self.temporary_directory.name) / "restored.sqlite3")
        result = second_store.import_backup(backup)
        self.assertEqual(result, {"created": 1, "updated": 0, "total": 1})
        restored = second_store.get(original["id"])
        self.assertEqual(restored["payload"]["points"][0]["address"], 20482)

    def test_rejects_invalid_profile_and_backup(self):
        with self.assertRaises(ValueError):
            self.store.save({"schema": "unknown"})
        with self.assertRaises(ValueError):
            self.store.import_backup({"schema": "unknown"})


class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        app_module._profile_store = ProfileStore(Path(self.temporary_directory.name) / "api.sqlite3")
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module._profile_store = None
        self.temporary_directory.cleanup()

    def test_library_endpoints(self):
        response = self.client.post("/api/profile-library", json={"profile": sample_profile()})
        self.assertEqual(response.status_code, 200)
        profile_id = response.get_json()["profile"]["id"]

        listed = self.client.get("/api/profile-library?q=PAC")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json()["profiles"][0]["id"], profile_id)

        loaded = self.client.get(f"/api/profile-library/{profile_id}")
        self.assertEqual(loaded.get_json()["payload"]["profile"]["manufacturer"], "Siemens")

        backup = self.client.get("/api/profile-library-backup")
        self.assertEqual(backup.get_json()["backup"]["profiles"][0]["metadata"]["id"], profile_id)

        deleted = self.client.delete(f"/api/profile-library/{profile_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/profile-library/{profile_id}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
