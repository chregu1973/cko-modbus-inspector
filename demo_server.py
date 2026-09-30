"""Kleines lokales Testgerät für den CKO Modbus Inspector.

Holding Register 0/1 enthalten den Float32-Wert 21.5 als ABCD.
Input Register 0/1 enthalten den Float32-Wert 12.75 als ABCD.
Standard: Modbus TCP auf Port 15020.
Mit --rtu-tcp: Modbus RTU über TCP auf Port 15021.
"""

import argparse

from pymodbus import FramerType
from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartTcpServer


def block(values):
    # ModbusDeviceContext translates protocol address 0 to datastore address 1.
    return ModbusSequentialDataBlock(1, values + [0] * (100 - len(values)))


device = ModbusDeviceContext(
    di=block([0, 1, 0, 1]),
    co=block([1, 0, 1, 0]),
    hr=block([0x41AC, 0x0000, 2300, 50]),
    ir=block([0x414C, 0x0000, 123, 456]),
)
context = ModbusServerContext(devices={1: device}, single=False)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rtu-tcp", action="store_true", help="RTU-Frames transparent über TCP testen")
    args = parser.parse_args()
    port = 15021 if args.rtu_tcp else 15020
    framer = FramerType.RTU if args.rtu_tcp else FramerType.SOCKET
    label = "Modbus RTU über TCP" if args.rtu_tcp else "Modbus TCP"
    print(f"Demo-Gerät: 127.0.0.1:{port} · Unit-ID 1 · {label}")
    StartTcpServer(context, address=("127.0.0.1", port), framer=framer)
