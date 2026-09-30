import tempfile
import unittest
from pathlib import Path

import app as app_module
from device_catalog import DeviceCatalogStore, ENTRY_SCHEMA, BACKUP_SCHEMA, SCHEMA_VERSION, DEFAULT_DEVICE_TYPE


def sample_entry(manufacturer="Fronius", model="Symo 3.7-3-M", device_type="wechselrichter"):
    return {
        "schema": ENTRY_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "manufacturer": manufacturer,
        "model": model,
        "aliases": "Symo 3.0-3-M / 4.5-3-M",
        "notes": "SunSpec Integer&SF, Datamanager 2.0.",
        "source_url": "https://example.com/fronius-modbus.pdf",
        "source_note": "Fronius Datamanager Register Map",
        "verified": False,
        "device_type": device_type,
        "points": [
            {
                "name": "AC-Wirkleistung",
                "quantity_kind": "power",
                "function": 3,
                "address": 40083,
                "data_type": "int16",
                "order": "",
                "scale": None,
                "scale_factor_address": 40084,
                "scale_factor_type": "power_of_ten",
                "unit": "W",
                "confidence": "hoch",
            },
            {
                "name": "Kaputter Punkt",
                "quantity_kind": "power",
                "data_type": "not-a-type",
            },
        ],
    }


class DeviceCatalogStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = DeviceCatalogStore(Path(self.temporary_directory.name) / "catalog.sqlite3")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_save_drops_invalid_points_but_keeps_valid_ones(self):
        saved = self.store.save(sample_entry())
        self.assertEqual(saved["manufacturer"], "Fronius")
        self.assertEqual(saved["point_count"], 1)
        loaded = self.store.get(saved["id"])
        self.assertEqual(loaded["payload"]["points"][0]["scale_factor_address"], 40084)

    def test_search_and_delete(self):
        saved = self.store.save(sample_entry())
        self.assertEqual(self.store.list("Fronius")[0]["id"], saved["id"])
        self.assertEqual(self.store.list("nope"), [])
        self.assertTrue(self.store.delete(saved["id"]))
        self.assertFalse(self.store.delete(saved["id"]))

    def test_rejects_entry_without_manufacturer_or_model(self):
        with self.assertRaises(ValueError):
            self.store.save({"schema": ENTRY_SCHEMA, "schema_version": SCHEMA_VERSION, "points": []})

    def test_rejects_wrong_schema(self):
        with self.assertRaises(ValueError):
            self.store.save({"schema": "unknown", "manufacturer": "X", "points": []})

    def test_invalid_device_type_falls_back_to_default(self):
        entry = sample_entry(device_type="not-a-real-type")
        saved = self.store.save(entry)
        self.assertEqual(saved["device_type"], DEFAULT_DEVICE_TYPE)

    def test_filter_by_device_type(self):
        self.store.save(sample_entry("Fronius", "Symo 3.7-3-M", device_type="wechselrichter"))
        self.store.save(sample_entry("Eastron", "SDM630", device_type="energiezaehler"))
        inverters = self.store.list(device_type="wechselrichter")
        self.assertEqual(len(inverters), 1)
        self.assertEqual(inverters[0]["manufacturer"], "Fronius")
        meters = self.store.list(device_type="energiezaehler")
        self.assertEqual(len(meters), 1)
        self.assertEqual(meters[0]["manufacturer"], "Eastron")

    def test_query_and_device_type_combine_with_and(self):
        self.store.save(sample_entry("Fronius", "Symo 3.7-3-M", device_type="wechselrichter"))
        self.store.save(sample_entry("Huawei", "SUN2000-5KTL", device_type="wechselrichter"))
        result = self.store.list(query="Fronius", device_type="wechselrichter")
        self.assertEqual(len(result), 1)
        result = self.store.list(query="Fronius", device_type="energiezaehler")
        self.assertEqual(result, [])

    def test_import_single_entry_creates_new(self):
        result = self.store.import_payload(sample_entry())
        self.assertEqual(result, {"created": 1, "updated": 0, "total": 1})
        self.assertEqual(len(self.store.list()), 1)

    def test_import_same_manufacturer_model_updates_existing(self):
        self.store.import_payload(sample_entry())
        entry = sample_entry()
        entry["notes"] = "Aktualisierte Notiz"
        result = self.store.import_payload(entry)
        self.assertEqual(result, {"created": 0, "updated": 1, "total": 1})
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.list()[0]["notes"], "Aktualisierte Notiz")

    def test_import_backup_with_multiple_entries(self):
        backup = {
            "schema": BACKUP_SCHEMA,
            "schema_version": SCHEMA_VERSION,
            "entries": [sample_entry("Fronius", "Symo 3.7-3-M"), sample_entry("Huawei", "SUN2000-5KTL")],
        }
        result = self.store.import_payload(backup)
        self.assertEqual(result, {"created": 2, "updated": 0, "total": 2})

    def test_import_rejects_unknown_schema(self):
        with self.assertRaises(ValueError):
            self.store.import_payload({"schema": "something-else"})


class DeviceCatalogApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        app_module._device_catalog_store = DeviceCatalogStore(Path(self.temporary_directory.name) / "api.sqlite3")
        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module._device_catalog_store = None
        self.temporary_directory.cleanup()

    def test_import_list_get_delete(self):
        imported = self.client.post("/api/device-catalog-import", json={"data": sample_entry()})
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(imported.get_json()["created"], 1)

        listed = self.client.get("/api/device-catalog?q=Fronius")
        self.assertEqual(listed.status_code, 200)
        entry_id = listed.get_json()["entries"][0]["id"]

        loaded = self.client.get(f"/api/device-catalog/{entry_id}")
        self.assertEqual(loaded.get_json()["payload"]["manufacturer"], "Fronius")

        deleted = self.client.delete(f"/api/device-catalog/{entry_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.client.get(f"/api/device-catalog/{entry_id}").status_code, 404)

    def test_import_invalid_payload_returns_400(self):
        response = self.client.post("/api/device-catalog-import", json={"data": {"schema": "nope"}})
        self.assertEqual(response.status_code, 400)

    def test_list_filters_by_type_query_param(self):
        self.client.post("/api/device-catalog-import", json={"data": sample_entry("Fronius", "Symo 3.7-3-M", "wechselrichter")})
        self.client.post("/api/device-catalog-import", json={"data": sample_entry("Eastron", "SDM630", "energiezaehler")})
        response = self.client.get("/api/device-catalog?type=energiezaehler")
        entries = response.get_json()["entries"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["manufacturer"], "Eastron")

    def test_device_catalog_types_endpoint(self):
        response = self.client.get("/api/device-catalog-types")
        data = response.get_json()
        self.assertTrue(data["ok"])
        values = [t["value"] for t in data["types"]]
        self.assertIn("wechselrichter", values)
        self.assertIn("sonstiges", values)


if __name__ == "__main__":
    unittest.main()


class BundledCatalogSeedTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = DeviceCatalogStore(Path(self.temporary_directory.name) / "seed.sqlite3")
        self.bundled = Path(__file__).resolve().parent.parent / "device-catalog-entries"

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_bundled_entries_are_added_once(self):
        added = self.store.seed_from_directory(self.bundled)
        self.assertGreaterEqual(added, 10)
        self.assertEqual(self.store.seed_from_directory(self.bundled), 0)
        self.assertTrue(self.store.list(query="Eastron"))

    def test_deleted_bundled_entry_does_not_come_back(self):
        self.store.seed_from_directory(self.bundled)
        entry = self.store.list(query="Fronius")[0]
        self.assertTrue(self.store.delete(entry["id"]))
        self.store.seed_from_directory(self.bundled)
        self.assertEqual(self.store.list(query="Fronius"), [])

    def test_existing_user_entry_is_not_overwritten(self):
        own = sample_entry()
        own.update({"manufacturer": "Eastron", "model": "SDM630 / SDM630MCT", "notes": "eigene Notiz"})
        self.store.import_payload(own)
        self.store.seed_from_directory(self.bundled)
        (entry,) = [item for item in self.store.list(query="SDM630") if item["model"] == "SDM630 / SDM630MCT"]
        self.assertEqual(self.store.get(entry["id"])["metadata"]["notes"], "eigene Notiz")

