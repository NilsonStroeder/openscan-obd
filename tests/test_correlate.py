"""Testa o motor de correlação (correlate.py) sem carro."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd import correlate  # noqa: E402


def _snap(label, lids):
    return correlate.Snapshot(module="tcm_cvt", label=label, timestamp="t",
                              session="0xC0", lids=lids)


class TestDiff(unittest.TestCase):
    def test_detects_changed_lid_and_byte(self) -> None:
        before = _snap("frio", {"0x80": "0a1b00", "0x81": "ffff"})
        after = _snap("quente", {"0x80": "0a4500", "0x81": "ffff"})
        diffs = correlate.diff_snapshots(before, after)
        self.assertEqual(len(diffs), 1)
        self.assertEqual(diffs[0].lid, "0x80")
        self.assertEqual(diffs[0].changed_byte_positions, [1])  # 2o byte mudou

    def test_no_change(self) -> None:
        a = _snap("x", {"0x80": "1234"})
        b = _snap("y", {"0x80": "1234"})
        self.assertEqual(correlate.diff_snapshots(a, b), [])

    def test_structural_change_when_length_differs(self) -> None:
        a = _snap("x", {"0x90": "1234"})
        b = _snap("y", {"0x90": "123456"})
        diffs = correlate.diff_snapshots(a, b)
        self.assertEqual(diffs[0].changed_byte_positions, [-1])

    def test_disappeared_lid_ignored(self) -> None:
        a = _snap("x", {"0x80": "11", "0x81": "22"})
        b = _snap("y", {"0x80": "11"})  # 0x81 sumiu
        self.assertEqual(correlate.diff_snapshots(a, b), [])

    def test_sorted_by_lid(self) -> None:
        a = _snap("x", {"0xa0": "00", "0x82": "00", "0x90": "00"})
        b = _snap("y", {"0xa0": "01", "0x82": "01", "0x90": "01"})
        order = [d.lid for d in correlate.diff_snapshots(a, b)]
        self.assertEqual(order, ["0x82", "0x90", "0xa0"])


class TestSaveLoad(unittest.TestCase):
    def test_roundtrip(self) -> None:
        snap = _snap("teste", {"0x80": "deadbeef"})
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "snap.json"
            correlate.save_snapshot(snap, p)
            loaded = correlate.load_snapshot(p)
        self.assertEqual(loaded.module, "tcm_cvt")
        self.assertEqual(loaded.lids["0x80"], "deadbeef")
        self.assertEqual(loaded.session, "0xC0")


class TestReport(unittest.TestCase):
    def test_report_mentions_changed_lid(self) -> None:
        before = _snap("frio", {"0x80": "0a1b"})
        after = _snap("quente", {"0x80": "0a45"})
        diffs = correlate.diff_snapshots(before, after)
        report = correlate.format_diff_report(before, after, diffs)
        self.assertIn("0x80", report)
        self.assertIn("frio", report)
        self.assertIn("quente", report)


if __name__ == "__main__":
    unittest.main()


class TestResponseId(unittest.TestCase):
    def test_expected_response_id(self) -> None:
        import importlib.util
        import pathlib
        # importa scanner so pra a funcao pura (nao chama hardware)
        spec = importlib.util.spec_from_file_location(
            "scanner_mod",
            pathlib.Path(__file__).resolve().parent.parent / "src" / "openscan_obd" / "scanner.py",
        )
        scanner_mod = importlib.util.module_from_spec(spec)
        sys.modules["scanner_mod"] = scanner_mod
        spec.loader.exec_module(scanner_mod)
        # faixa OBD padrao -> +8
        self.assertEqual(scanner_mod.expected_response_id(0x7E0), 0x7E8)
        self.assertEqual(scanner_mod.expected_response_id(0x7E1), 0x7E9)
        # enhanced Nissan -> +0x20
        self.assertEqual(scanner_mod.expected_response_id(0x740), 0x760)
        self.assertEqual(scanner_mod.expected_response_id(0x742), 0x762)
        self.assertEqual(scanner_mod.expected_response_id(0x74D), 0x76D)
        # candidatos: OBD padrao so +8; fora dele +0x20 e +0x10 (0x71E->0x72E)
        self.assertEqual(scanner_mod.candidate_response_ids(0x7E1), [0x7E9])
        self.assertEqual(scanner_mod.candidate_response_ids(0x745), [0x765, 0x755])
        self.assertIn(0x72E, scanner_mod.candidate_response_ids(0x71E))
        # IDs acima de 0x7FF (11 bits) sao descartados
        self.assertEqual(scanner_mod.candidate_response_ids(0x7F0), [])
