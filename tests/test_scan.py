"""Scan sob demanda (SDD 5.6): leitura apenas, tudo cru + decodificado, sem inventar."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from openscan_obd.gateway.j2534_mock import J2534DeviceMock
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
from openscan_obd.gateway.scan import run_scan, save_scan


class Recorder:
    """Embrulha o mock, registra o que foi enviado e quais IDs estavam ativos."""

    data_source = "recorded_fixture"

    def __init__(self, absent_tx=(), fail_tcm_lid=False, no_3e_tx=(), no_kwp17=False) -> None:
        self.mock = J2534DeviceMock()
        self.mock.open()
        self.sent: list[tuple[int, bytes]] = []
        self.absent_tx = set(absent_tx)
        self.fail_tcm_lid = fail_tcm_lid
        self.no_3e_tx = set(no_3e_tx)         # módulos KWP que só respondem dentro de sessão (10 C0)
        self.no_kwp17 = no_kwp17
        self.tx = 0x7E0

    def open(self) -> None: ...
    def close(self) -> None: ...

    def set_ids(self, tx: int, rx: int) -> None:
        self.tx = tx
        self.mock.set_ids(tx, rx)

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.sent.append((self.tx, bytes(data)))
        if self.tx in self.absent_tx:
            raise TimeoutError("ERR_TIMEOUT")
        if self.fail_tcm_lid and self.tx == 0x7E1 and data[:2] == b"\x21\x01":
            raise RuntimeError("DLL falhou")
        if data[:1] == b"\x3e" and self.tx in self.no_3e_tx:
            raise TimeoutError("ERR_TIMEOUT")
        if data[:1] == b"\x17" and self.no_kwp17:
            return bytes([0x7F, 0x17, 0x12])
        return self.mock.send_recv(data, timeout_ms)


class TestScan(unittest.TestCase):
    def test_module_presence_and_absence(self) -> None:
        dev = Recorder(absent_tx={0x745})                      # BCM não responde
        res = run_scan(dev)
        mods = res["modules"]
        self.assertTrue(mods["engine"]["present"])
        self.assertTrue(mods["tcm_cvt"]["present"])
        self.assertFalse(mods["bcm"]["present"])
        self.assertEqual(mods["bcm"]["status"], "timeout")
        self.assertIn("catálogo", res["catalog_note"].lower())

    def test_ecm_supported_pids_and_live_snapshot(self) -> None:
        res = run_scan(Recorder())
        ecm = res["ecm"]
        self.assertIn(0x0C, ecm["supported_pids"])
        self.assertIn(0x42, ecm["supported_pids"])
        self.assertEqual(ecm["live"]["rpm"]["value"], 710.0)
        self.assertEqual(ecm["live"]["rpm"]["raw"], "410c0b18")

    def test_vin_is_not_requested_when_bitmap_does_not_declare_it(self) -> None:
        dev = Recorder()
        res = run_scan(dev)
        self.assertEqual(res["ecm"]["vin"]["status"], "nao_suportado")
        self.assertNotIn(b"\x09\x02", [d for _, d in dev.sent])

    def test_ecm_dtcs_are_listed_with_raw(self) -> None:
        res = run_scan(Recorder())
        d = res["ecm"]["dtcs"]
        self.assertEqual((d["stored"], d["pending"]), ([], []))
        self.assertEqual(d["raw"], {"03": "4300", "07": "4700"})

    def test_tcm_snapshot_is_decoded_and_raw_is_kept(self) -> None:
        res = run_scan(Recorder())
        tcm = res["tcm"]
        self.assertEqual(tcm["lid01"]["decoded"]["gear"], "P")
        self.assertEqual(len(bytes.fromhex(tcm["lid01"]["raw"])), 69)

    def test_cvt_dtc_is_never_reported_as_clean_while_unvalidated(self) -> None:
        res = run_scan(Recorder(no_kwp17=True))                 # nenhuma tentativa devolveu códigos
        dtc = res["tcm"]["dtc"]
        self.assertEqual(dtc["status"], "nao_validado")
        self.assertIn("attempts", dtc)
        self.assertEqual(dtc["codes"], [])
        self.assertEqual(res["summary"]["dtc_cvt"], "nao_validado")

    def test_cvt_dtc_codes_from_kwp_17_are_a_hypothesis_with_raw(self) -> None:
        # Gravado no carro em 2026-11-16: TCM responde 17 FF 00 com 3 códigos.
        res = run_scan(Recorder())
        dtc = res["tcm"]["dtc"]
        self.assertEqual(dtc["status"], "hipotese_nao_validada")
        self.assertEqual([c["code"] for c in dtc["codes"]], ["P0725", "U1000", "P1722"])
        self.assertEqual(dtc["kwp_17"]["response"], "57030725f1d000a71722f1")
        self.assertIn("hipótese", dtc["reason"])
        self.assertEqual(res["summary"]["dtc_cvt"], "hipotese_nao_validada")
        self.assertEqual(res["summary"]["dtc_cvt_codes"], ["P0725", "U1000", "P1722"])

    def test_modules_that_ignore_tester_present_are_found_by_session_request(self) -> None:
        # 2026-11-16: EPS/painel/BCM responderam a 10 C0 (catálogo de ontem) mas não a 3E.
        res = run_scan(Recorder(no_3e_tx={0x742, 0x743, 0x745}))
        for name in ("eps", "meter", "bcm"):
            with self.subTest(module=name):
                self.assertTrue(res["modules"][name]["present"])
                self.assertEqual(res["modules"][name]["probe"], "10c0")
        self.assertEqual(res["modules"]["engine"]["probe"], "3e")

    def test_failure_in_one_step_is_recorded_and_ids_are_restored(self) -> None:
        dev = Recorder(fail_tcm_lid=True)
        res = run_scan(dev)
        self.assertEqual(res["tcm"]["lid01"]["status"], "error")
        self.assertIn("DLL falhou", res["tcm"]["lid01"]["error"])
        self.assertTrue(res["ecm"]["supported_pids"])           # o resto do scan seguiu
        self.assertEqual(dev.tx, 0x7E0)                          # voltou para o ECM

    def test_device_without_set_ids_skips_other_modules(self) -> None:
        class NoSet:
            data_source = "x"

            def __init__(self) -> None:
                self.m = J2534DeviceMock()
                self.m.open()

            def send_recv(self, data, timeout_ms=200):
                return self.m.send_recv(data, timeout_ms)

        res = run_scan(NoSet())
        self.assertTrue(res["ecm"]["supported_pids"])
        self.assertEqual(res["tcm"]["status"], "skipped")
        self.assertEqual(res["modules"]["bcm"]["status"], "skipped")

    def test_scan_only_sends_read_only_requests(self) -> None:
        dev = ReadOnlyDevice(Recorder())                         # a guarda levantaria erro
        res = run_scan(dev)
        self.assertNotIn("error", res["ecm"].get("dtcs", {}))
        self.assertTrue(res["ecm"]["supported_pids"])

    def test_progress_callback_reports_each_step(self) -> None:
        steps = []
        run_scan(Recorder(), progress=steps.append)
        self.assertEqual(steps, ["modulos", "ecm", "tcm", "outros"])


class TestSaveScan(unittest.TestCase):
    def test_writes_json_and_never_overwrites(self) -> None:
        res = run_scan(Recorder())
        with tempfile.TemporaryDirectory() as d:
            p1 = save_scan(res, Path(d), stamp="20261115_190000")
            p2 = save_scan(res, Path(d), stamp="20261115_190000")
            self.assertNotEqual(p1, p2)
            self.assertTrue(p1.name.startswith("scan_20261115_190000"))
            self.assertEqual(json.loads(p1.read_text(encoding="utf-8"))["schema"], 1)


if __name__ == "__main__":
    unittest.main()
