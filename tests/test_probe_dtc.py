"""probe-dtc (SDD 5.5, F4): hipóteses de leitura de DTC do TCM, só leitura, resultado cru."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openscan_obd.gateway.j2534_mock import J2534DeviceMock
from openscan_obd.gateway.probe_dtc import run_probe
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice, ReadOnlyViolation
from openscan_obd.gateway.scan import save_scan


class Recorder:
    data_source = "recorded_fixture"

    def __init__(self, a3_reply: dict | None = None) -> None:
        self.mock = J2534DeviceMock()
        self.mock.open()
        self.sent: list[tuple[int, bytes]] = []
        self.tx = 0x7E0
        self.a3_reply = a3_reply or {}        # tx -> bytes (ou exceção) para o SID A3

    def open(self) -> None: ...
    def close(self) -> None: ...

    def set_ids(self, tx: int, rx: int) -> None:
        self.tx = tx
        self.mock.set_ids(tx, rx)

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.sent.append((self.tx, bytes(data)))
        if data[:1] == b"\xa3":
            reply = self.a3_reply.get(self.tx, bytes([0x7F, 0xA3, 0x11]))
            if isinstance(reply, Exception):
                raise reply
            return reply
        return self.mock.send_recv(data, timeout_ms)

    def requests(self) -> list[bytes]:
        return [d for _, d in self.sent]


class TestProbeDtc(unittest.TestCase):
    def test_h1_obd_dtc_modes_on_the_tcm_are_recorded_raw(self) -> None:
        res = run_probe(Recorder())
        h1 = res["H1"]["tcm"]
        self.assertEqual(set(h1), {"03", "07", "0A"})
        self.assertEqual(h1["03"]["response"], "4300")           # cru, sem interpretar
        self.assertIn(h1["0A"]["status"], ("nrc", "timeout", "no_response", "ok"))

    def test_h2_functional_broadcast_uses_7df_and_ids_are_restored(self) -> None:
        dev = Recorder()
        res = run_probe(dev)
        self.assertIn((0x7DF, b"\x03"), dev.sent)
        self.assertEqual(set(res["H2"]), {"03", "07", "0A"})
        self.assertEqual(dev.tx, 0x7E0)

    def test_h3_tcm_17ff00_reply_is_recorded_raw_from_the_mock(self) -> None:
        res = run_probe(Recorder())
        self.assertEqual(res["H3"]["tcm"]["requests"]["17ff00"]["response"],
                         "57030725f1d000a71722f1")
        self.assertEqual(res["H3"]["ecm"]["requests"]["17ff00"]["nrc"], "12")

    def test_h3_kwp_13_and_17_on_ecm_and_tcm_under_session_c0(self) -> None:
        dev = Recorder()
        res = run_probe(dev)
        for module in ("ecm", "tcm"):
            with self.subTest(module=module):
                h3 = res["H3"][module]
                self.assertEqual(h3["session"]["request"], "10c0")
                self.assertEqual(set(h3["requests"]), {"13", "13ff00", "17", "17ff00"})
        sent = dev.requests()
        self.assertIn(b"\x13\xff\x00", sent)
        self.assertIn(b"\x17", sent)

    def test_a3_is_not_sent_by_default(self) -> None:
        dev = Recorder()
        res = run_probe(dev)
        self.assertNotIn(b"\xa3", dev.requests())
        self.assertEqual(res["H5"]["status"], "skipped")

    def test_a3_requires_parked_confirmation_even_with_allow_flag(self) -> None:
        dev = Recorder()
        res = run_probe(dev, allow_a3=True, confirm_parked=False)
        self.assertNotIn(b"\xa3", dev.requests())
        self.assertEqual(res["H5"]["status"], "refused")
        self.assertIn("parado", res["H5"]["reason"])

    def test_a3_runs_one_request_per_module_after_h1_to_h3(self) -> None:
        dev = Recorder()
        res = run_probe(dev, allow_a3=True, confirm_parked=True)
        a3 = [(tx, d) for tx, d in dev.sent if d[:1] == b"\xa3"]
        self.assertEqual(a3, [(0x7E0, b"\xa3"), (0x7E1, b"\xa3")])
        last_h3 = max(i for i, (_, d) in enumerate(dev.sent) if d[:1] in (b"\x13", b"\x17"))
        first_a3 = min(i for i, (_, d) in enumerate(dev.sent) if d[:1] == b"\xa3")
        self.assertGreater(first_a3, last_h3)                    # só depois de H1–H3
        self.assertEqual(res["H5"]["ecm"]["status"], "nrc")
        self.assertEqual(res["H5"]["tcm"]["status"], "nrc")

    def test_a3_stops_at_the_first_unexpected_response(self) -> None:
        dev = Recorder(a3_reply={0x7E0: bytes.fromhex("aabbcc")})   # nem positiva nem NRC
        res = run_probe(dev, allow_a3=True, confirm_parked=True)
        self.assertEqual(res["H5"]["ecm"]["status"], "unexpected")
        self.assertEqual(res["H5"]["tcm"]["status"], "stopped")
        self.assertEqual([d for _, d in dev.sent if d[:1] == b"\xa3"], [b"\xa3"])

    def test_a3_positive_reply_is_recorded_not_interpreted(self) -> None:
        dev = Recorder(a3_reply={0x7E0: bytes.fromhex("e3010203"), 0x7E1: bytes.fromhex("e3")})
        res = run_probe(dev, allow_a3=True, confirm_parked=True)
        self.assertEqual(res["H5"]["ecm"]["status"], "ok")
        self.assertEqual(res["H5"]["ecm"]["response"], "e3010203")
        self.assertIn("hipótese", res["H5"]["note"])

    def test_guard_blocks_a3_unless_explicitly_extra_allowed(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            run_probe(ReadOnlyDevice(Recorder()), allow_a3=True, confirm_parked=True)
        res = run_probe(ReadOnlyDevice(Recorder(), extra_allowed={0xA3}),
                        allow_a3=True, confirm_parked=True)
        self.assertEqual(res["H5"]["ecm"]["status"], "nrc")

    def test_default_probe_runs_clean_under_the_read_only_guard(self) -> None:
        res = run_probe(ReadOnlyDevice(Recorder()))
        self.assertEqual(res["H5"]["status"], "skipped")

    def test_result_is_json_serializable_and_saved_with_probe_prefix(self) -> None:
        res = run_probe(Recorder())
        with tempfile.TemporaryDirectory() as d:
            path = save_scan(res, Path(d), stamp="20261115_200000", prefix="probe_dtc")
            self.assertTrue(path.name.startswith("probe_dtc_20261115_200000"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema"], 1)


class TestProbeCommandParses(unittest.TestCase):
    def test_cli_command_exists_with_safe_defaults(self) -> None:
        from openscan_obd.cli import main as cli_main

        cmd = cli_main.commands["probe-dtc"]
        ctx = cmd.make_context("probe-dtc", ["--dll", "x.dll"])
        self.assertFalse(ctx.params["allow_a3"])
        self.assertFalse(ctx.params["confirm_parked"])


if __name__ == "__main__":
    unittest.main()
