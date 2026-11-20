"""Resposta KWP atrasada (eco de LID diferente do pedido) não pode ser gravada com o rótulo errado."""
import unittest

from openscan_obd.gateway.collect import read_lid


class Dev:
    data_source = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.timeouts = []

    def send_recv(self, data, timeout_ms=200):
        self.timeouts.append(timeout_ms)
        r = self.script.pop(0)
        if r is None:
            raise TimeoutError("t")
        return bytes.fromhex(r)


class ReadLidTests(unittest.TestCase):
    def test_matching_echo_is_ok_without_retry(self):
        d = Dev(["610200aa"])
        r = read_lid(d, 0x02, 150)
        self.assertEqual((r["status"], r["echo"]), ("ok", "02"))
        self.assertEqual(len(d.timeouts), 1)

    def test_stale_echo_retries_once_with_longer_timeout(self):
        d = Dev(["610100aa", "610200bb"])
        r = read_lid(d, 0x02, 150)
        self.assertEqual(r["response"], "610200bb")
        self.assertEqual(r["echo"], "02")
        self.assertGreater(d.timeouts[1], d.timeouts[0])
        self.assertEqual(r["stale"], "610100aa")

    def test_persistent_mismatch_is_flagged_not_hidden(self):
        d = Dev(["610100aa", "610100aa"])
        r = read_lid(d, 0x02, 150)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["echo"], "01")
        self.assertTrue(r["mismatch"])

    def test_timeout_retries_with_longer_window_when_asked(self):
        d = Dev([None, "610500cc"])
        r = read_lid(d, 0x05, 150, retry_timeout=True)
        self.assertEqual((r["status"], r["echo"]), ("ok", "05"))
        self.assertGreater(d.timeouts[1], d.timeouts[0])

    def test_timeout_without_retry_stays_timeout(self):
        self.assertEqual(read_lid(Dev([None]), 0x05, 150)["status"], "timeout")

    def test_nrc_and_timeout_pass_through(self):
        self.assertEqual(read_lid(Dev(["7f2112"]), 0x05, 150)["status"], "nrc")
        self.assertEqual(read_lid(Dev([None]), 0x05, 150)["status"], "timeout")


if __name__ == "__main__":
    unittest.main()
