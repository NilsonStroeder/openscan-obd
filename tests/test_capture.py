from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from openscan_obd.cli import main
from openscan_obd.gateway.capture import JsonlFrameCapture


class TestJsonlFrameCapture(unittest.TestCase):
    def test_writes_metadata_frames_and_stop_marker_as_json_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            capture = JsonlFrameCapture(path, {"vehicle": "Sentra B16"})
            capture.open()
            capture.write_frame({
                "conn": True,
                "lid_available": True,
                "raw_lid01": "001b0000",
            })
            capture.close()

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual([record["event"] for record in records], [
            "capture_started", "frame", "capture_stopped",
        ])
        self.assertEqual(records[0]["schema_version"], 1)
        self.assertEqual(records[0]["metadata"]["vehicle"], "Sentra B16")
        self.assertEqual(records[1]["frame"]["raw_lid01"], "001b0000")

    def test_refuses_to_overwrite_existing_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            path.write_text("keep", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                JsonlFrameCapture(path, {}).open()

            self.assertEqual(path.read_text(encoding="utf-8"), "keep")

    def test_dashboard_cli_passes_capture_metadata_to_api(self) -> None:
        capture_path = Path("logs") / "field.jsonl"
        with patch("openscan_obd.api.main.main") as run_api:
            result = CliRunner().invoke(main, [
                "dashboard",
                "--hardware",
                "--capture", str(capture_path),
                "--vehicle", "Sentra B16 2010",
                "--ecu", "ECM",
                "--adapter", "GODIAG GD101",
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        run_api.assert_called_once_with(
            host="127.0.0.1",
            port=8000,
            mock=False,
            dll_path=None,
            capture_path=capture_path,
            capture_metadata={
                "vehicle": "Sentra B16 2010",
                "ecu": "ECM",
                "adapter": "GODIAG GD101",
            },
            elm_port=None,
            profile=None,
        )

    def test_dashboard_elm_option_implies_hardware(self) -> None:
        with patch("openscan_obd.api.main.main") as run_api:
            result = CliRunner().invoke(main, ["dashboard", "--elm", "COM5"])

        self.assertEqual(result.exit_code, 0, result.output)
        kwargs = run_api.call_args.kwargs
        self.assertFalse(kwargs["mock"])
        self.assertEqual(kwargs["elm_port"], "COM5")


if __name__ == "__main__":
    unittest.main()
