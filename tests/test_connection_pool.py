import unittest

from connection_pool import BACKOFF_STEPS, ConnectionPool, ConnectionUnavailable


class Target:
    def __init__(self, host="10.0.0.5", port=502, transport="tcp", timeout=0.8):
        self.host, self.port, self.transport, self.timeout = host, port, transport, timeout


class FakeClient:
    instances = []

    def __init__(self, ok=True):
        self.ok, self.closed, self.calls = ok, False, 0
        FakeClient.instances.append(self)

    def connect(self):
        return self.ok

    def close(self):
        self.closed = True


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        FakeClient.instances = []
        self.clock = Clock()
        self.ok = True
        self.pool = ConnectionPool(lambda target: FakeClient(self.ok), clock=self.clock)

    def test_one_connection_is_shared_by_all_users(self):
        for user in ("Decoder", "Live-Monitor", "Unit-Scan"):
            with self.pool.session(Target(), user) as handle:
                handle.call(lambda client: None)
        self.assertEqual(len(FakeClient.instances), 1)
        status = self.pool.status()[0]
        self.assertTrue(status["open"])
        self.assertEqual(status["requests"], 3)
        self.assertEqual(status["users"], ["Decoder", "Live-Monitor", "Unit-Scan"])

    def test_connection_error_closes_and_next_use_reconnects(self):
        def broken(client):
            raise ConnectionResetError("reset by peer")

        with self.pool.session(Target(), "Live-Monitor") as handle:
            with self.assertRaises(ConnectionResetError):
                handle.call(broken)
        self.assertTrue(FakeClient.instances[0].closed)
        with self.pool.session(Target(), "Live-Monitor") as handle:
            handle.call(lambda client: None)
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertEqual(self.pool.status()[0]["reconnects"], 1)

    def test_failed_connect_backs_off_before_next_attempt(self):
        self.ok = False
        with self.assertRaises(ConnectionUnavailable) as first:
            with self.pool.session(Target(), "Decoder"):
                pass
        self.assertIn("Home Assistant, Node-RED", str(first.exception))
        attempts = len(FakeClient.instances)
        with self.assertRaises(ConnectionUnavailable) as second:
            with self.pool.session(Target(), "Decoder"):
                pass
        self.assertIn("nächster Versuch", str(second.exception))
        self.assertEqual(len(FakeClient.instances), attempts)  # während der Wartezeit kein neuer Verbindungsversuch
        self.clock.now += BACKOFF_STEPS[0] + 0.1
        self.ok = True
        with self.pool.session(Target(), "Decoder"):
            pass
        self.assertEqual(self.pool.status()[0]["retry_in_s"], 0)

    def test_idle_connection_is_closed(self):
        with self.pool.session(Target(), "Decoder"):
            pass
        self.clock.now += 61
        self.pool.close_idle()
        self.assertFalse(self.pool.status()[0]["open"])

    def test_changed_timeout_rebuilds_instead_of_second_session(self):
        with self.pool.session(Target(timeout=0.8), "Decoder"):
            pass
        with self.pool.session(Target(timeout=2.0), "Decoder"):
            pass
        self.assertEqual(len(FakeClient.instances), 2)
        self.assertTrue(FakeClient.instances[0].closed)
        self.assertEqual(sum(1 for client in FakeClient.instances if not client.closed), 1)

    def test_fresh_session_reconnects(self):
        with self.pool.session(Target(), "Unit-Scan"):
            pass
        with self.pool.session(Target(), "Unit-Scan", fresh=True):
            pass
        self.assertEqual(len(FakeClient.instances), 2)

    def test_different_targets_get_separate_connections(self):
        with self.pool.session(Target(host="10.0.0.5"), "A"):
            pass
        with self.pool.session(Target(host="10.0.0.6"), "B"):
            pass
        self.assertEqual(len(self.pool.status()), 2)
