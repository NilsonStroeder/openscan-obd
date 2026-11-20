from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from openscan_obd.cli import main
from openscan_obd.gateway.capture_visualization import (
    export_capture_csv,
    generate_capture_comparison_report,
    generate_capture_report,
)


class TestCaptureVisualization(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.capture = self.root / "capture.jsonl"
        self.metadata = {
            "mode": "j2534",
            "vehicle": "Sentra B16 2010",
            "ecu": "ECM",
            "adapter": "GODIAG GD101",
            "vehicle_profile": "sentra_b16_test_vehicle",
            "validation_status": "not_validated",
        }

    def write_capture(
        self,
        frames: list[dict],
        metadata: dict | None = None,
        capture_path: Path | None = None,
    ) -> None:
        records = [{
            "event": "capture_started",
            "schema_version": 1,
            "captured_at": "2026-10-25T12:00:00+00:00",
            "metadata": metadata or self.metadata,
        }]
        for index, frame in enumerate(frames):
            timestamp = datetime.fromisoformat("2026-10-25T12:00:00+00:00").timestamp() + index
            frame.setdefault("ts", timestamp)
            records.append({
                "event": "frame",
                "captured_at": datetime.fromtimestamp(timestamp).astimezone().isoformat(),
                "frame": frame,
            })
        last_ts = records[-1]["frame"]["ts"] if frames else datetime.fromisoformat(
            "2026-10-25T12:00:00+00:00"
        ).timestamp()
        records.append({
            "event": "capture_stopped",
            "captured_at": datetime.fromtimestamp(last_ts + 1).astimezone().isoformat(),
        })
        (capture_path or self.capture).write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_exports_csv_with_raw_values_and_unverified_decoder_state(self) -> None:
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "raw_lid01": "0001000203",
            "data_source": "j2534",
            "profile": "sdd_b17_ecm_lid01",
            "verified": False,
            "rpm": 850.0,
            "vsp": 42.5,
            "ign_adv": 10.5,
            "o2s1": 0.91,
        }])
        output = self.root / "capture.csv"

        count = export_capture_csv(self.capture, output)

        with output.open(encoding="utf-8", newline="") as csv_file:
            row = next(csv.DictReader(csv_file))
        self.assertEqual(count, 1)
        self.assertEqual(row["elapsed_s"], "0.0")
        self.assertEqual(row["vehicle"], self.metadata["vehicle"])
        self.assertEqual(row["raw_lid01_hex"], "0001000203")
        self.assertEqual(row["profile"], "sdd_b17_ecm_lid01")
        self.assertEqual(row["verified"], "False")
        self.assertEqual(row["rpm"], "850.0")
        self.assertEqual(row["vsp"], "42.5")
        self.assertEqual(row["ign_adv"], "10.5")
        self.assertEqual(row["o2s1"], "0.91")
        self.assertEqual(row["ect"], "")

    def test_html_report_has_signal_controls_and_breaks_missing_samples(self) -> None:
        self.write_capture([
            {
                "conn": True,
                "lid_available": True,
                "raw_lid01": "0001",
                "profile": "sdd_b17_ecm_lid01",
                "verified": False,
                "rpm": 800.0,
                "o2s1": 0.4,
            },
            {
                "conn": False,
                "lid_available": False,
                "raw_lid01": None,
            },
            {
                "conn": True,
                "lid_available": True,
                "raw_lid01": "0002",
                "profile": "sdd_b17_ecm_lid01",
                "verified": False,
                "rpm": 900.0,
                "o2s1": 0.6,
            },
        ])
        output = self.root / "report.html"

        count = generate_capture_report(self.capture, output)
        html = output.read_text(encoding="utf-8")

        self.assertEqual(count, 3)
        self.assertIn("O2S1 — tensão hipotética, não AFR/lambda", html)
        self.assertIn("sdd_b17_ecm_lid01", html)
        self.assertIn('"verified": false', html)
        self.assertIn('"conn": false, "lid_available": false', html)
        self.assertIn("Segmentos são separados em falhas", html)
        self.assertIn("Lacunas de conexão", html)
        self.assertNotIn("https://", html)

    def test_html_report_escapes_untrusted_metadata_before_script_embedding(self) -> None:
        self.write_capture(
            [{
                "conn": True,
                "lid_available": True,
                "raw_lid01": "abcd",
                "rpm": 700,
            }],
            metadata={
                **self.metadata,
                "vehicle": "</script><script>alert(1)</script>__SIGNALS__",
            },
        )
        output = self.root / "safe.html"

        generate_capture_report(self.capture, output)

        html = output.read_text(encoding="utf-8")
        self.assertNotIn("</script><script>alert(1)", html)
        self.assertIn("\\u003c/script\\u003e", html)
        self.assertIn("__SIGNALS__", html)

    def test_cli_creates_csv_and_html_reports(self) -> None:
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "raw_lid01": "abcd",
            "rpm": 700,
        }])
        csv_path = self.root / "out.csv"
        html_path = self.root / "out.html"
        runner = CliRunner()

        csv_result = runner.invoke(main, [
            "export-capture-csv", str(self.capture), "--out", str(csv_path),
        ])
        html_result = runner.invoke(main, [
            "plot-capture", str(self.capture), "--out", str(html_path),
        ])

        self.assertEqual(csv_result.exit_code, 0, csv_result.output)
        self.assertEqual(html_result.exit_code, 0, html_result.output)
        self.assertTrue(csv_path.exists())
        self.assertTrue(html_path.exists())

    def test_comparison_report_overlays_common_signals_and_aligns_elapsed_time(self) -> None:
        second_capture = self.root / "second.jsonl"
        self.write_capture(
            [
                {
                    "conn": True, "lid_available": True, "rpm": 700.0, "vsp": 0.0,
                    "profile": "profile_a", "verified": False,
                },
                {
                    "conn": True, "lid_available": True, "rpm": 800.0, "vsp": 10.0,
                    "profile": "profile_a", "verified": False,
                },
            ],
            capture_path=self.capture,
        )
        self.write_capture(
            [
                {
                    "conn": True, "lid_available": True, "rpm": 900.0, "vsp": 0.0,
                    "profile": "profile_b", "verified": True,
                },
                {
                    "conn": True, "lid_available": True, "rpm": 1000.0, "vsp": 20.0,
                    "profile": "profile_b", "verified": True,
                },
            ],
            metadata={**self.metadata, "vehicle": "Outro veículo"},
            capture_path=second_capture,
        )
        output = self.root / "comparison.html"

        counts = generate_capture_comparison_report(
            self.capture, second_capture, output,
        )
        html = output.read_text(encoding="utf-8")
        comparison_data = html.split("const COMPARISON = ", 1)[1].split(";\n", 1)[0]
        comparison = json.loads(comparison_data)

        self.assertEqual(counts, (2, 2))
        self.assertIn("Atenção: diferenças detectadas", html)
        self.assertIn("differences.join", html)
        self.assertIn("RPM (hipótese)", html)
        self.assertIn('"elapsed_s": 0.0', html)
        self.assertEqual(comparison["captures"][0]["frames"][1]["elapsed_s"], 1.0)
        self.assertEqual(comparison["captures"][1]["frames"][1]["elapsed_s"], 1.0)
        self.assertEqual(comparison["captures"][0]["decoder_profiles"], ["profile_a"])
        self.assertEqual(comparison["captures"][1]["verified_states"], ["True"])
        self.assertIn("perfil do decoder", html)
        self.assertIn("estado verified", html)
        self.assertIn('"rpm"', html)
        self.assertNotIn("https://", html)

    def test_comparison_report_handles_captures_without_common_signals(self) -> None:
        second_capture = self.root / "second.jsonl"
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "rpm": 700.0,
        }])
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "vsp": 12.0,
        }], capture_path=second_capture)
        output = self.root / "no-common-signals.html"

        generate_capture_comparison_report(self.capture, second_capture, output)

        html = output.read_text(encoding="utf-8")
        self.assertIn("Não há sinais numéricos em comum", html)

    def test_comparison_cli_creates_report(self) -> None:
        second_capture = self.root / "second.jsonl"
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "rpm": 700.0,
        }])
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "rpm": 800.0,
        }], capture_path=second_capture)
        output = self.root / "compare.html"

        result = CliRunner().invoke(main, [
            "compare-captures", str(self.capture), str(second_capture),
            "--out", str(output),
        ])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue(output.exists())
        self.assertIn("1 frames na primeira; 1 na segunda", result.output)

    def test_comparison_report_refuses_to_overwrite_existing_output(self) -> None:
        second_capture = self.root / "second.jsonl"
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "rpm": 700.0,
        }])
        self.write_capture([{
            "conn": True,
            "lid_available": True,
            "rpm": 800.0,
        }], capture_path=second_capture)
        output = self.root / "existing.html"
        output.write_text("keep", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            generate_capture_comparison_report(
                self.capture, second_capture, output,
            )

        self.assertEqual(output.read_text(encoding="utf-8"), "keep")

    def test_report_refuses_to_overwrite_existing_output(self) -> None:
        self.write_capture([])
        output = self.root / "report.html"
        output.write_text("keep", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            generate_capture_report(self.capture, output)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
