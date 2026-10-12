import unittest

import app as app_module
from device_catalog import DeviceCatalogStore
from loxone_import import LoxoneImportError, convert

SAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<Modbus Title="Swegon Gold RX" Comment="" HintText="" Baudrate="19200" Stopbits="1" Channel="1">
  <Info templateType="7" minVersion="16000610"/>
  <ModbusCmd Title="Zulufttemperatur" ModbusAddress="12" ModbusCmd="3" ModbusDataType="1" Unit="&lt;v.1&gt; °C" Analog="true" Sensor="true" SourceValHigh="10" DestValHigh="1"/>
  <ModbusCmd Title="Leistung" ModbusAddress="100" ModbusCmd="4" ModbusDataType="36" Unit="&lt;v&gt; kW" SourceValHigh="1000" DestValHigh="1"/>
  <ModbusCmd Title="Energie" ModbusAddress="200" ModbusCmd="3" ModbusDataType="164" Unit="&lt;v.2&gt; kWh"/>
  <ModbusCmd Title="Störung" ModbusAddress="5" ModbusCmd="2" Unit="" Analog="false" Sensor="true"/>
  <ModbusCmd Title="Sollwert" ModbusAddress="30" ModbusCmd="6" ModbusDataType="0" Unit="&lt;v.1&gt; °C" SourceValHigh="10" DestValHigh="1" Sensor="false"/>
  <ModbusCmd Title="Offset-Sensor" ModbusAddress="40" ModbusCmd="3" ModbusDataType="1" SourceValLow="0" SourceValHigh="100" DestValLow="-40" DestValHigh="60"/>
</Modbus>"""


class LoxoneImportTests(unittest.TestCase):
    def test_types_orders_scaling_and_units(self):
        entry = convert(SAMPLE, "swegon.xml")
        points = {p["name"]: p for p in entry["points"]}
        self.assertEqual((entry["manufacturer"], entry["model"]), ("Swegon", "Gold RX"))
        self.assertEqual(points["Zulufttemperatur"], {**points["Zulufttemperatur"], "function": 3, "address": 12, "data_type": "int16", "order": "AB", "scale": 0.1, "unit": "°C", "quantity_kind": "temperature"})
        self.assertEqual((points["Leistung"]["data_type"], points["Leistung"]["order"], points["Leistung"]["scale"]), ("float32", "CDAB", 0.001))
        self.assertEqual((points["Energie"]["data_type"], points["Energie"]["order"]), ("float32", "DCBA"))
        self.assertEqual((points["Störung"]["function"], points["Störung"]["data_type"]), (2, "bool"))
        self.assertEqual(points["Sollwert"]["function"], 3)
        self.assertIn("Schreibbefehl", points["Sollwert"]["caveats"])
        self.assertIn("Offset -40", points["Offset-Sensor"]["caveats"])
        self.assertIn("Baudrate 19200", entry["notes"])
        self.assertIn("nicht weitergeben", entry["source_note"])

    def test_entry_is_accepted_by_catalog(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            store = DeviceCatalogStore(Path(folder) / "c.sqlite3")
            result = store.import_payload(convert(SAMPLE, "swegon.xml"))
            self.assertEqual(result["created"], 1)
            entry = store.list(query="Swegon")[0]
            self.assertEqual(store.get(entry["id"])["metadata"]["point_count"], 6)

    def test_invalid_files(self):
        for text in ("<x/>", "kein xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><Modbus/>'):
            with self.assertRaises(LoxoneImportError):
                convert(text)

    def test_api(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            app_module._device_catalog_store = DeviceCatalogStore(Path(folder) / "api.sqlite3")
            try:
                data = app_module.app.test_client().post("/api/device-catalog-import-loxone", json={"xml": SAMPLE, "filename": "swegon.xml"}).get_json()
                self.assertTrue(data["ok"])
                self.assertEqual(data["points"], 6)
            finally:
                app_module._device_catalog_store = None
