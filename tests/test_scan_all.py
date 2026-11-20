"""Varredura longa de IDs CAN (só leitura): acha módulos em qualquer par tx/rx testado."""
from __future__ import annotations

import unittest

from openscan_obd.gateway.j2534 import J2534Error
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
from openscan_obd.gateway.scan_all import run_scan_all


class FakeBus:
    """Módulos só respondem quando o par (tx, rx) bate; o resto dá timeout."""
    data_source = "fake"

    def __init__(self, modules: dict[tuple[int, int], dict]) -> None:
        self.modules = modules
        self.ids = (0x7E0, 0x7E8)
        self.sent: list[tuple[tuple[int, int], bytes]] = []
        self.set_calls: list[tuple[int, int]] = []

    def set_ids(self, tx: int, rx: int) -> None:
        self.ids = (tx, rx)
        self.set_calls.append((tx, rx))

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.sent.append((self.ids, bytes(data)))
        mod = self.modules.get(self.ids)
        if mod is None:
            raise TimeoutError("ERR_TIMEOUT")
        reply = mod.get(bytes(data))
        if reply is None:
            return bytes([0x7F, data[0], 0x11])
        return reply


ABS = {b"\x10\xc0": b"\x50\xc0", b"\x1a\x80": bytes.fromhex("5a80414253"),
       b"\x17\xff\x00": bytes.fromhex("5700")}


class LeakyBus(FakeBus):
    """Como o GD101 real: depois de ~N trocas de filtro, PassThruStopMsgFilter passa a falhar
    (ERR_INVALID_MSG) até o canal ser reaberto."""

    def __init__(self, modules, limit=20) -> None:
        super().__init__(modules)
        self.limit = limit
        self.swaps = 0
        self.reopens = 0

    def reset_channel(self) -> None:
        self.swaps = 0
        self.reopens += 1

    def set_ids(self, tx: int, rx: int) -> None:
        if self.swaps >= self.limit:
            raise J2534Error(0x1A, "PassThruStopMsgFilter: ERR_INVALID_MSG: OK")
        self.swaps += 1
        super().set_ids(tx, rx)


class TestScanAll(unittest.TestCase):
    def test_survives_filter_exhaustion_by_reopening_the_channel(self) -> None:
        # Carro 2026-11-16: "Error: PassThruStopMsgFilter: ERR_INVALID_MSG" em 0x62x derrubou a varredura.
        bus = LeakyBus({(0x7A0, 0x7B0): ABS}, limit=20)
        res = run_scan_all(ReadOnlyDevice(bus), tx_range=(0x600, 0x7A5))   # ~422 IDs x 3 trocas
        self.assertEqual([f["tx"] for f in res["found"]], ["0x7A0"])
        self.assertGreater(bus.reopens, 1)
        self.assertEqual(res["summary"]["tested_tx"], 0x7A5 - 0x600 + 1)
        self.assertEqual(res["summary"]["errors"], 0)

    def test_unrecoverable_adapter_error_is_recorded_and_scan_keeps_partial_result(self) -> None:
        class Dead(LeakyBus):
            def reset_channel(self) -> None:
                raise J2534Error(0x08, "PassThruConnect: ERR_DEVICE_NOT_CONNECTED")
        bus = Dead({}, limit=0)
        res = run_scan_all(ReadOnlyDevice(bus), tx_range=(0x600, 0x640))
        self.assertTrue(res["summary"]["aborted"])
        self.assertIn("ERR_DEVICE_NOT_CONNECTED", res["summary"]["abort_reason"])
        self.assertLess(res["summary"]["tested_tx"], 0x41)

    def test_finds_module_at_non_default_offset_and_records_raw(self) -> None:
        bus = FakeBus({(0x740, 0x750): ABS})                      # +0x10
        res = run_scan_all(ReadOnlyDevice(bus), tx_range=(0x73F, 0x742))
        self.assertEqual([f["tx"] for f in res["found"]], ["0x740"])
        f = res["found"][0]
        self.assertEqual(f["rx"], "0x750")
        self.assertEqual(f["offset"], "+0x10")
        self.assertEqual(f["requests"]["1a80"]["response"], "5a80414253")
        self.assertEqual(f["requests"]["17ff00"]["response"], "5700")
        self.assertEqual(res["summary"]["found"], 1)
        self.assertEqual(res["summary"]["tested_tx"], 4)

    def test_empty_dtc_list_is_not_reported_as_healthy(self) -> None:
        res = run_scan_all(ReadOnlyDevice(FakeBus({(0x740, 0x760): ABS})), tx_range=(0x740, 0x740))
        self.assertIn("não prova", res["found"][0]["note"])

    def test_nrc_to_session_still_proves_presence(self) -> None:
        bus = FakeBus({(0x742, 0x762): {b"\x10\xc0": bytes([0x7F, 0x10, 0x12])}})
        res = run_scan_all(ReadOnlyDevice(bus), tx_range=(0x742, 0x742))
        self.assertEqual(res["found"][0]["session"]["status"], "nrc")

    def test_silence_everywhere_finds_nothing(self) -> None:
        res = run_scan_all(ReadOnlyDevice(FakeBus({})), tx_range=(0x700, 0x703))
        self.assertEqual(res["found"], [])
        self.assertEqual(res["summary"]["found"], 0)

    def test_only_allowed_read_requests_are_sent_and_ids_are_restored(self) -> None:
        bus = FakeBus({(0x740, 0x760): ABS})
        run_scan_all(ReadOnlyDevice(bus), tx_range=(0x73E, 0x741))      # ReadOnlyViolation se algo vazar
        sids = {data[0] for _, data in bus.sent}
        self.assertLessEqual(sids, {0x10, 0x1A, 0x17, 0x13, 0x21, 0x3E, 0x01})
        self.assertEqual(bus.ids, (0x7E0, 0x7E8))

    def test_stops_trying_offsets_after_first_hit(self) -> None:
        bus = FakeBus({(0x740, 0x748): ABS})                     # +0x08 vem primeiro
        run_scan_all(ReadOnlyDevice(bus), tx_range=(0x740, 0x740))
        tried = {rx for tx, rx in bus.set_calls if tx == 0x740}
        self.assertEqual(tried, {0x748})

    def test_keyboard_interrupt_keeps_partial_result(self) -> None:
        class Boom(FakeBus):
            def send_recv(self, data, timeout_ms=200):
                if self.ids[0] == 0x702:
                    raise KeyboardInterrupt
                return super().send_recv(data, timeout_ms)
        bus = Boom({(0x700, 0x720): ABS})
        res = run_scan_all(ReadOnlyDevice(bus), tx_range=(0x700, 0x705))
        self.assertTrue(res["summary"]["interrupted"])
        self.assertEqual(len(res["found"]), 1)
        self.assertEqual(bus.ids, (0x7E0, 0x7E8))

    def test_on_update_gets_partial_result_after_each_tx_so_a_hang_loses_nothing(self) -> None:
        snaps: list[tuple[int, int]] = []
        run_scan_all(ReadOnlyDevice(FakeBus({(0x701, 0x721): ABS})), tx_range=(0x700, 0x703),
                     on_update=lambda r: snaps.append((r["summary"]["tested_tx"], len(r["found"]))))
        self.assertEqual(snaps, [(1, 0), (2, 1), (3, 1), (4, 1), (4, 1)])      # o último é o resultado final

    def test_progress_reports_every_tx(self) -> None:
        seen: list[int] = []
        run_scan_all(ReadOnlyDevice(FakeBus({})), tx_range=(0x700, 0x702),
                     progress=lambda tx, total: seen.append(tx))
        self.assertEqual(seen, [0x700, 0x701, 0x702])


if __name__ == "__main__":
    unittest.main()


class TestScanAllCli(unittest.TestCase):
    def test_cli_defaults_to_one_offset_and_writes_partial_file_every_id(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from click.testing import CliRunner

        from openscan_obd.cli import main

        bus = FakeBus({(0x701, 0x721): ABS})
        bus.open = lambda: None
        bus.close = lambda: None
        with tempfile.TemporaryDirectory() as tmp, \
                patch("openscan_obd.gateway.j2534.J2534Device", return_value=bus):
            res = CliRunner().invoke(main, ["scan-all", "--dll", "x.dll", "--start", "700",
                                            "--end", "703", "--out-dir", tmp])
            self.assertEqual(res.exit_code, 0, res.output)
            files = list(Path(tmp).glob("scan_all_*.json"))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["rx_offsets"], ["+0x20"])
        self.assertEqual([f["tx"] for f in data["found"]], ["0x701"])
        self.assertEqual({rx for (_, rx) in bus.set_calls if rx != 0x7E8} - {0x720, 0x721, 0x722, 0x723}, set())
