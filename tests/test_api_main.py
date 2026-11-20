"""Estrutura FastAPI do gateway — mock, sem hardware."""
from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from openscan_obd.api.main import create_app
from openscan_obd.gateway.j2534_mock import J2534DeviceMock


class OneShotReadTimeoutDevice:
    data_source = "test_mock"

    def __init__(self) -> None:
        self.device = J2534DeviceMock()
        self.read_count = 0

    def open(self) -> None:
        self.device.open()

    def close(self) -> None:
        self.device.close()

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        if data[:1] == b"\x21":
            self.read_count += 1
        if data[:1] == b"\x21" and self.read_count == 2:
            raise TimeoutError("transient LID read timeout")
        return self.device.send_recv(data, timeout_ms)


class TestApiMain(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(mock=True)
        self.client = TestClient(self.app)

    def test_root_is_served(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_cors_allows_any_origin(self) -> None:
        response = self.client.get("/", headers={"Origin": "http://example.test"})
        self.assertEqual(response.headers.get("access-control-allow-origin"), "*")

    def test_lifespan_starts_poller(self) -> None:
        with TestClient(self.app) as client:
            self.assertTrue(hasattr(client.app.state, "poller"))
            self.assertIsNotNone(client.app.state.poller)

    def test_websocket_reports_transient_failure_and_recovery(self) -> None:
        device = OneShotReadTimeoutDevice()
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "recovery.jsonl"
            with patch("openscan_obd.api.main._make_device", return_value=device):
                with TestClient(create_app(mock=True, capture_path=capture_path)) as client:
                    with client.websocket_connect("/ws/live") as websocket:
                        initial = websocket.receive_json()
                        failed = websocket.receive_json()
                        recovered = websocket.receive_json()

                    self.assertTrue(initial["conn"])
                    self.assertTrue(initial["lid_available"])
                    self.assertEqual(initial["raw_lid01"], "001b0000")
                    self.assertFalse(failed["conn"])
                    self.assertFalse(failed["lid_available"])
                    self.assertIsNone(failed["raw_lid01"])
                    self.assertNotIn("rpm", failed)
                    self.assertIn("transient LID read timeout", failed["error"])
                    self.assertTrue(recovered["conn"])
                    self.assertTrue(recovered["lid_available"])
                    self.assertEqual(recovered["raw_lid01"], "001b0000")
                    self.assertTrue(client.get("/api/status").json()["session_active"])
                    self.assertTrue(client.get("/api/params").json()["conn"])

            frames = [
                record["frame"]
                for record in map(
                    json.loads, capture_path.read_text(encoding="utf-8").splitlines(),
                )
                if record["event"] == "frame"
            ]

        self.assertTrue(any("transient LID read timeout" in frame.get("error", "") for frame in frames))

    def test_websocket_streams_independently_to_multiple_clients(self) -> None:
        with TestClient(create_app(mock=True)) as client:
            with client.websocket_connect("/ws/live") as first:
                with client.websocket_connect("/ws/live") as second:
                    first_frame = first.receive_json()
                    second_frame = second.receive_json()

        self.assertTrue(first_frame["conn"])
        self.assertTrue(second_frame["conn"])
        self.assertEqual(first_frame["data_source"], "recorded_fixture")
        self.assertEqual(second_frame["data_source"], "recorded_fixture")

    def test_capture_records_metadata_and_raw_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            capture_path = Path(temp_dir) / "field.jsonl"
            app = create_app(
                mock=True,
                capture_path=capture_path,
                capture_metadata={
                    "vehicle": "Sentra B16 2010",
                    "ecu": "ECM",
                    "adapter": "GODIAG GD101",
                },
            )
            with TestClient(app) as client:
                self.assertTrue(client.get("/api/status").json()["capture_enabled"])
                with client.websocket_connect("/ws/live") as websocket:
                    frame = websocket.receive_json()
                self.assertTrue(frame["conn"])

            records = [
                json.loads(line)
                for line in capture_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(records[0]["event"], "capture_started")
        self.assertEqual(records[0]["metadata"]["vehicle"], "Sentra B16 2010")
        self.assertEqual(records[0]["metadata"]["adapter"], "GODIAG GD101")
        self.assertEqual(records[0]["metadata"]["validation_status"], "not_validated")
        frame_records = [record for record in records if record["event"] == "frame"]
        self.assertTrue(frame_records)
        self.assertEqual(frame_records[0]["frame"]["raw_lid01"], "001b0000")
        self.assertIn("cycle_ms", frame_records[0]["frame"]["timing"])   # F2: latência na captura
        self.assertEqual(records[-1]["event"], "capture_stopped")


if __name__ == "__main__":
    unittest.main()


class TestApiReadOnlyGuard(unittest.TestCase):
    def test_lifespan_wraps_the_adapter_in_the_read_only_guard(self) -> None:
        from openscan_obd.gateway.readonly_guard import ReadOnlyDevice, ReadOnlyViolation

        with TestClient(create_app(mock=True)) as client:
            device = client.app.state.device
            self.assertIsInstance(device, ReadOnlyDevice)
            with self.assertRaises(ReadOnlyViolation):
                device.send_recv(b"\x04")                 # limpar DTCs nunca passa
            self.assertEqual(device.send_recv(b"\x01\x0c"), bytes.fromhex("410c0b18"))
