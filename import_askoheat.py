#!/usr/bin/env python3
"""Import Askoheat AHFR-BI-plus-5.8 into device catalog database."""

import json
from pathlib import Path
from device_catalog import DeviceCatalogStore

catalog_file = Path(__file__).parent / "device-catalog-entries" / "askoheat-ahfr-bi-plus-5-8.hbdevicecatalog.json"

try:
    with open(catalog_file, 'r', encoding='utf-8') as f:
        catalog_data = json.load(f)

    print(f"[INFO] Loading: {catalog_file.name}")

    store = DeviceCatalogStore()
    result = store.import_payload(catalog_data)

    print(f"\n[SUCCESS] Import complete!")
    print(f"[RESULT] Created: {result['created']} | Updated: {result['updated']} | Total: {result['total']}")

    entries = store.list(query="Askoheat", limit=5)
    if entries:
        print(f"\n[DATABASE] Askoheat entries:")
        for entry in entries:
            print(f"  - {entry['manufacturer']} {entry['model']}")
            print(f"    Type: {entry['device_type']} | Datapoints: {entry['point_count']}")
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()
