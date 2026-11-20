from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from openscan_obd.cli import main
from openscan_obd.gateway.capture_analysis import (
    format_capture_summary,
    summarize_capture,
)


class TestCaptureAnalysis(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.path = Path(self.temp_dir.name) / "field.jsonl"

    def write_records(self, records: list[dict]) -> None:
        for record in records:
            if record["event"] == "capture_started":
                record.setdefault("schema_version", 1)
                record.setdefault("metadata", {})
            if record["event"] == "frame":
                record["frame"].setdefault(
                    "ts",
                    datetime.fromisoformat(
                        record["captured_at"].replace("Z", "+00:00")
                    ).timestamp(),
                )
        self.path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_summarizes_outages_recoveries_lid_gaps_and_raw_changes(self) -> None:
        self.write_records([
            {
                "event": "capture_started",
                "captured_at": "2026-10-25T12:00:00+00:00",
                "metadata": {"vehicle": "Sentra B16"},
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01+00:00",
                "frame": {"conn": True, "lid_available": True, "raw_lid01": "0102"},
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:03+00:00",
                "frame": {"conn": True, "lid_available": False, "raw_lid01": None},
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:04+00:00",
                "frame": {"conn": False, "lid_available": False, "raw_lid01": None},
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:11+00:00",
                "frame": {"conn": True, "lid_available": True, "raw_lid01": "0304"},
            },
            {
                "event": "capture_stopped",
                "captured_at": "2026-10-25T12:00:13+00:00",
            },
        ])

        summary = summarize_capture(self.path)

        self.assertEqual(summary["metadata"], {"vehicle": "Sentra B16"})
        self.assertEqual(summary["duration_s"], 13.0)
        self.assertTrue(summary["complete"])
        self.assertEqual(summary["frame_count"], 4)
        self.assertEqual(summary["connected_frames"], 3)
        self.assertEqual(summary["disconnected_frames"], 1)
        self.assertEqual(summary["connection_outages"], 1)
        self.assertEqual(summary["recoveries"], 1)
        self.assertEqual(summary["connection_outage_durations_s"], [7.0])
        self.assertEqual(summary["max_connection_outage_s"], 7.0)
        self.assertEqual(summary["connection_outages_detail"][0]["ongoing"], False)
        self.assertEqual(summary["lid_available_frames"], 2)
        self.assertEqual(summary["lid_missing_frames"], 1)
        self.assertEqual(summary["lid_missing_periods"], 1)
        self.assertEqual(summary["unique_raw_lid01_payloads"], 2)
        self.assertEqual(summary["raw_lid01_payload_changes"], 1)
        self.assertEqual(summary["raw_lid01_payloads"], ["0102", "0304"])
        self.assertEqual(summary["frame_interval_count"], 3)
        self.assertEqual(summary["frame_interval_min_s"], 1.0)
        self.assertEqual(summary["frame_interval_p50_s"], 2.0)
        self.assertEqual(summary["frame_interval_p95_s"], 7.0)
        self.assertEqual(summary["frame_interval_max_s"], 7.0)
        self.assertEqual(summary["max_frame_gap_s"], 7.0)
        self.assertEqual(
            summary["frame_timing_source"],
            "frame.ts (Unix timestamp do poller)",
        )
        self.assertIn("sem decodificação", format_capture_summary(summary))

    def test_reads_capture_with_and_without_raw_tcm_lid01_field(self) -> None:
        def frames(extra: dict) -> list[dict]:
            return [
                {"event": "capture_started", "captured_at": "2026-11-18T12:00:00+00:00"},
                {"event": "frame", "captured_at": "2026-11-18T12:00:01+00:00",
                 "frame": {"conn": True, "lid_available": True, "raw_lid01": "0102", **extra}},
                {"event": "frame", "captured_at": "2026-11-18T12:00:02+00:00",
                 "frame": {"conn": True, "lid_available": True, "raw_lid01": "0102"}},
                {"event": "capture_stopped", "captured_at": "2026-11-18T12:00:03+00:00"},
            ]

        self.write_records(frames({}))
        without = summarize_capture(self.path)
        self.write_records(frames({"raw_tcm_lid01": "6101" + "00" * 68}))
        with_field = summarize_capture(self.path)
        self.write_records(frames({"raw_tcm_lid01": None}))
        with_none = summarize_capture(self.path)
        self.assertEqual(without, with_field)
        self.assertEqual(without, with_none)
        result = CliRunner().invoke(main, ["analyze-capture", str(self.path)])
        self.assertEqual(result.exit_code, 0, result.output)

    def test_marks_capture_without_stop_marker_incomplete(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
        ])

        summary = summarize_capture(self.path)

        self.assertFalse(summary["complete"])
        self.assertEqual(summary["frame_count"], 0)
        self.assertEqual(summary["duration_s"], 0)

    def test_reports_unrecovered_outage_as_ongoing_at_capture_end(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {"conn": False, "lid_available": False, "raw_lid01": None},
            },
            {
                "event": "capture_stopped",
                "captured_at": "2026-10-25T12:00:06Z",
            },
        ])

        summary = summarize_capture(self.path)

        self.assertEqual(summary["connection_outage_durations_s"], [5.0])
        self.assertEqual(summary["connection_outages_detail"][0]["ended_at"], None)
        self.assertTrue(summary["connection_outages_detail"][0]["ongoing"])

    def test_uses_poller_timestamp_for_frame_intervals(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {
                    "ts": datetime.fromisoformat("2026-10-25T12:00:05+00:00").timestamp(),
                    "conn": True,
                    "lid_available": True,
                    "raw_lid01": "abcd",
                },
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:02Z",
                "frame": {
                    "ts": datetime.fromisoformat("2026-10-25T12:00:10+00:00").timestamp(),
                    "conn": True,
                    "lid_available": True,
                    "raw_lid01": "abcd",
                },
            },
            {"event": "capture_stopped", "captured_at": "2026-10-25T12:00:11Z"},
        ])

        summary = summarize_capture(self.path)

        self.assertEqual(summary["frame_interval_max_s"], 5.0)

    def test_rejects_invalid_json_with_line_number(self) -> None:
        self.path.write_text(
            '{"event":"capture_started","captured_at":"2026-10-25T12:00:00Z"}\n'
            '{invalid}\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "linha 2: JSON inválido"):
            summarize_capture(self.path)

    def test_rejects_missing_schema_version(self) -> None:
        self.path.write_text(
            '{"event":"capture_started","captured_at":"2026-10-25T12:00:00Z"}\n',
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "schema_version deve ser inteiro"):
            summarize_capture(self.path)

    def test_rejects_missing_capture_metadata(self) -> None:
        self.write_records([{
            "event": "capture_started",
            "captured_at": "2026-10-25T12:00:00Z",
        }])
        records = [json.loads(line) for line in self.path.read_text(
            encoding="utf-8",
        ).splitlines()]
        del records[0]["metadata"]
        self.path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "metadata deve ser um objeto JSON"):
            summarize_capture(self.path)

    def test_rejects_unsupported_schema_version(self) -> None:
        self.write_records([{
            "event": "capture_started",
            "schema_version": 2,
            "captured_at": "2026-10-25T12:00:00Z",
        }])

        with self.assertRaisesRegex(ValueError, "versão de schema não suportada: 2"):
            summarize_capture(self.path)

    def test_rejects_boolean_schema_version(self) -> None:
        self.write_records([{
            "event": "capture_started",
            "schema_version": True,
            "captured_at": "2026-10-25T12:00:00Z",
        }])

        with self.assertRaisesRegex(ValueError, "schema_version deve ser inteiro"):
            summarize_capture(self.path)

    def test_rejects_out_of_order_frame_timestamps(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {"ts": 1792929602, "conn": True, "lid_available": True},
            },
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:02Z",
                "frame": {"ts": 1792929601, "conn": True, "lid_available": True},
            },
        ])

        with self.assertRaisesRegex(ValueError, "frame inválido: ts fora de ordem"):
            summarize_capture(self.path)

    def test_rejects_non_string_event_names(self) -> None:
        self.write_records([{
            "event": [],
            "captured_at": "2026-10-25T12:00:00Z",
        }])

        with self.assertRaisesRegex(ValueError, "evento desconhecido"):
            summarize_capture(self.path)

    def test_rejects_invalid_frame_profile_type(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {
                    "ts": 1792929601,
                    "conn": True,
                    "lid_available": True,
                    "profile": [],
                },
            },
        ])

        with self.assertRaisesRegex(ValueError, "profile deve ser string ou null"):
            summarize_capture(self.path)

    def test_rejects_non_boolean_verified_state(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {
                    "ts": 1792929601,
                    "conn": True,
                    "lid_available": True,
                    "verified": "false",
                },
            },
        ])

        with self.assertRaisesRegex(ValueError, "verified deve ser boolean ou null"):
            summarize_capture(self.path)

    def test_cli_reports_invalid_capture_as_user_error(self) -> None:
        self.path.write_text("{invalid}\n", encoding="utf-8")

        result = CliRunner().invoke(main, ["analyze-capture", str(self.path)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("linha 1: JSON inválido", result.output)

    def test_cli_reports_unsupported_schema_as_user_error(self) -> None:
        self.write_records([{
            "event": "capture_started",
            "schema_version": 2,
            "captured_at": "2026-10-25T12:00:00Z",
        }])

        result = CliRunner().invoke(main, ["analyze-capture", str(self.path)])

        self.assertEqual(result.exit_code, 1)
        self.assertIn("versão de schema não suportada: 2", result.output)

    def test_cli_can_emit_structured_json(self) -> None:
        self.write_records([
            {"event": "capture_started", "captured_at": "2026-10-25T12:00:00Z"},
            {
                "event": "frame",
                "captured_at": "2026-10-25T12:00:01Z",
                "frame": {"conn": True, "lid_available": True, "raw_lid01": "abcd"},
            },
            {"event": "capture_stopped", "captured_at": "2026-10-25T12:00:02Z"},
        ])

        result = CliRunner().invoke(main, ["analyze-capture", str(self.path), "--json"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(json.loads(result.output)["raw_lid01_payloads"], ["abcd"])


if __name__ == "__main__":
    unittest.main()
