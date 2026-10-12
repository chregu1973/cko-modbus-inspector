import pytest

import modbus_core


@pytest.fixture(autouse=True)
def _fresh_connection_pool():
    # Jeder Test beginnt ohne offene gemeinsame Verbindung
    modbus_core.POOL.reset()
    yield
    modbus_core.POOL.reset()
