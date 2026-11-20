"""Comando field-test — offline e ao vivo com snapshot falso, sem hardware.

O comando ficou quebrado (ImportError) desde o commit 82b82a9, que removeu
capture_and_analyze/run_analysis de field_tests.py; estes testes evitam que
isso volte sem ser notado.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from click.testing import CliRunner  # noqa: E402

from openscan_obd import field_tests  # noqa: E402
from openscan_obd.cli import main  # noqa: E402

FIELD = Path(__file__).resolve().parent / "fixtures" / "lid01_field_20261023.json"
PAYLOAD_HEX = json.loads(FIELD.read_text(encoding="utf-8"))["captures"][0]["hex"]


class TestRunAnalysis(unittest.TestCase):
    def test_offline_cli_with_hex(self) -> None:
        spaced = " ".join(PAYLOAD_HEX[i:i + 2] for i in range(0, len(PAYLOAD_HEX), 2))
        result = CliRunner().invoke(main, ["field-test", "--scenario", "P", "--hex", spaced])
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        self.assertIn("AVISO", result.output)
        self.assertIn(PAYLOAD_HEX[:8], result.output.replace(" ", ""))

    def test_rejects_wrong_length_and_unknown_scenario(self) -> None:
        with self.assertRaises(ValueError):
            field_tests.run_analysis("P", bytes(68))
        with self.assertRaises(ValueError):
            field_tests.run_analysis("xyz", bytes.fromhex(PAYLOAD_HEX))


class TestCaptureAndAnalyze(unittest.TestCase):
    def test_live_mode_uses_snapshot_of_lid01(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snapshot.json"

            def fake_snapshot(dll, module, label, start, end):
                calls.append((dll, module, label, start, end))
                snap.write_text(json.dumps({"lids": {"0x01": PAYLOAD_HEX}}), encoding="utf-8")
                return snap

            with patch("openscan_obd.scanner.snapshot_lids", fake_snapshot):
                result = CliRunner().invoke(main, ["field-test", "--dll", "fake.dll",
                                                   "--scenario", "D", "--label", "seletor_D_1"])
        self.assertEqual(result.exit_code, 0, result.output + repr(result.exception))
        self.assertEqual(calls, [("fake.dll", "tcm_cvt", "seletor_D_1", 0x01, 0x01)])

    def test_live_mode_without_lid01_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            snap = Path(tmp) / "snapshot.json"
            snap.write_text(json.dumps({"lids": {}}), encoding="utf-8")
            with patch("openscan_obd.scanner.snapshot_lids", lambda *a: snap):
                with self.assertRaises(RuntimeError):
                    field_tests.capture_and_analyze("P", "fake.dll")


if __name__ == "__main__":
    unittest.main()
