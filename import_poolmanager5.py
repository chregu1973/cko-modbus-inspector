#!/usr/bin/env python3
"""
Import Bayrol Poolmanager 5 into the local device catalog database.
"""

import json
import sys
import os
from pathlib import Path

os.environ['PYTHONIOENCODING'] = 'utf-8'

from device_catalog import DeviceCatalogStore


def import_poolmanager5():
    """Load and import Bayrol Poolmanager 5 catalog entry."""

    catalog_file = Path(__file__).parent / "device-catalog-entries" / "bayrol-poolmanager-5.hbdevicecatalog.json"

    if not catalog_file.exists():
        print(f"[FAIL] Catalog file not found: {catalog_file}")
        return False

    try:
        with open(catalog_file, 'r', encoding='utf-8') as f:
            catalog_data = json.load(f)

        print(f"[INFO] Loading catalog from: {catalog_file}")
        print(f"[INFO] Schema: {catalog_data.get('schema')}")

        store = DeviceCatalogStore()
        result = store.import_payload(catalog_data)

        print(f"\n[SUCCESS] Import successful!")
        print(f"[RESULT] Created: {result['created']} new entries")
        print(f"[RESULT] Updated: {result['updated']} existing entries")
        print(f"[RESULT] Total:   {result['total']} entries processed")

        entries = store.list(query="Bayrol", device_type="sonstiges", limit=10)
        if entries:
            print(f"\n[CATALOG] Bayrol entries in database:")
            for entry in entries:
                print(f"  - {entry['manufacturer']} {entry['model']}")
                print(f"    Type: {entry['device_type']}")
                print(f"    Datapoints: {entry['point_count']}")

        return True

    except json.JSONDecodeError as e:
        print(f"[FAIL] JSON parsing error: {e}")
        return False
    except Exception as e:
        print(f"[FAIL] Import error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = import_poolmanager5()
    sys.exit(0 if success else 1)
