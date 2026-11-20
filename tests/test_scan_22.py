"""Varredura de DIDs do serviço 0x22 (só leitura), por trás da guarda e em sessão C0."""
from __future__ import annotations

import unittest

from openscan_obd.gateway.readonly_guard import ReadOnlyDevice, ReadOnlyViolation
from openscan_obd.gateway.scan_22 import run_scan_22


class Bus:
    data_source = "fake"

    def __init__(self, dids: dict[int, bytes], service_ok=True, only_in_session=False) -> None:
        self.dids = dids
        self.service_ok = service_ok
        self.only_in_session = only_in_session
        self.in_session = False
        self.sent: list[bytes] = []
        self.ids = None

    def set_ids(self, tx, rx):
        self.ids = (tx, rx)

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        data = bytes(data)
        self.sent.append(data)
        if data[:2] == b"\x10\xc0":
            self.in_session = True
            return b"\x50\xc0"
        if data[0] == 0x22:
            if not self.service_ok or (self.only_in_session and not self.in_session):
                return bytes([0x7F, 0x22, 0x11])
            did = int.from_bytes(data[1:3], "big")
            if did in self.dids:
                return b"\x62" + data[1:3] + self.dids[did]
            if did == 0x1ED0:
                return bytes([0x7F, 0x22, 0x22])               # condições incorretas: DID existe
            return bytes([0x7F, 0x22, 0x31])
        raise TimeoutError("ERR_TIMEOUT")


def run(bus, **kw):
    kw.setdefault("did_range", (0x1EB0, 0x1EFF))
    return run_scan_22(ReadOnlyDevice(bus, extra_allowed={0x22}), 0x7E1, 0x7E9, **kw)


class TestScan22(unittest.TestCase):
    def test_finds_dids_with_raw_data_and_records_interesting_nrcs(self) -> None:
        res = run(Bus({0x1EBC: bytes.fromhex("07b2"), 0x1EC0: bytes.fromhex("0bb7")}))
        self.assertEqual({f["did"]: f["data"] for f in res["found"]},
                         {"0x1EBC": "07b2", "0x1EC0": "0bb7"})
        self.assertEqual(res["nrc_dids"]["22"], ["0x1ED0"])          # existe mas recusou
        self.assertNotIn("31", res["nrc_dids"])                       # fora de faixa só é contado
        self.assertGreater(res["nrc_counts"]["31"], 0)

    def test_stops_early_when_service_22_is_not_supported(self) -> None:
        bus = Bus({}, service_ok=False)
        res = run(bus, did_range=(0x0000, 0xFFFF))
        self.assertEqual(res["summary"]["verdict"], "servico_22_nao_suportado")
        self.assertLess(sum(1 for d in bus.sent if d[0] == 0x22), 40)

    def test_session_c0_is_tried_before_giving_up(self) -> None:
        bus = Bus({0x1EBC: b"\x07\xb2"}, only_in_session=True)
        res = run(bus)
        self.assertEqual([f["did"] for f in res["found"]], ["0x1EBC"])
        self.assertTrue(res["summary"]["session_c0"])

    def test_no_session_option_skips_10_c0(self) -> None:
        bus = Bus({}, service_ok=True)
        run(bus, use_session=False)
        self.assertNotIn(b"\x10\xc0", bus.sent)

    def test_only_service_22_and_session_c0_are_ever_sent(self) -> None:
        bus = Bus({0x1EBC: b"\x07\xb2"})
        run(bus)
        self.assertEqual({d[0] for d in bus.sent}, {0x10, 0x22})

    def test_guard_still_blocks_writes_even_with_22_enabled(self) -> None:
        guarded = ReadOnlyDevice(Bus({}), extra_allowed={0x22})
        with self.assertRaises(ReadOnlyViolation):
            guarded.send_recv(b"\x2e\x1e\xbc\x00")
        with self.assertRaises(ReadOnlyViolation):
            guarded.send_recv(b"\x27\x01")

    def test_without_extra_the_guard_refuses_22(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            ReadOnlyDevice(Bus({})).send_recv(b"\x22\x1e\xbc")

    def test_on_update_called_and_ids_restored(self) -> None:
        snaps = []
        bus = Bus({0x1EBC: b"\x07\xb2"})
        run(bus, on_update=lambda r: snaps.append(r["summary"]["tested"]))
        self.assertTrue(snaps)
        self.assertEqual(bus.ids, (0x7E0, 0x7E8))

    def test_keyboard_interrupt_keeps_partial(self) -> None:
        class Boom(Bus):
            def send_recv(self, data, timeout_ms=200):
                if data[0] == 0x22 and int.from_bytes(data[1:3], "big") == 0x1EC0:
                    raise KeyboardInterrupt
                return super().send_recv(data, timeout_ms)
        res = run(Boom({0x1EBC: b"\x07\xb2"}))
        self.assertTrue(res["summary"]["interrupted"])
        self.assertEqual([f["did"] for f in res["found"]], ["0x1EBC"])


class TestScan22Cli(unittest.TestCase):
    def test_cli_writes_json_with_found_dids(self) -> None:
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from click.testing import CliRunner

        from openscan_obd.cli import main

        bus = Bus({0x1EBC: bytes.fromhex("07b2")})
        bus.open = lambda: None
        bus.close = lambda: None
        with tempfile.TemporaryDirectory() as tmp, \
                patch("openscan_obd.gateway.j2534.J2534Device", return_value=bus):
            res = CliRunner().invoke(main, ["scan-22", "--dll", "x.dll", "--start", "1EB0",
                                            "--end", "1ECF", "--out-dir", tmp])
            self.assertEqual(res.exit_code, 0, res.output)
            data = json.loads(next(Path(tmp).glob("scan_22_7E1_*.json")).read_text(encoding="utf-8"))
        self.assertEqual([f["did"] for f in data["found"]], ["0x1EBC"])
        self.assertIn("DID 0x1EBC = 07b2", res.output)


if __name__ == "__main__":
    unittest.main()
