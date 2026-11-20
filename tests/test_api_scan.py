"""Endpoints de scan: POST /api/scan, GET /api/scan, /api/dtcs após o scan."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from openscan_obd.api.main import create_app


def wait_done(client: TestClient, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get("/api/scan").json()
        if body["state"] in ("done", "error"):
            return body
        time.sleep(0.02)
    raise AssertionError("scan não terminou")


class TestApiScan(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = create_app(mock=True, scan_dir=Path(self.tmp.name))

    def test_scan_dir_can_come_from_the_environment(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"NISSAN_SCANNER_SCAN_DIR": self.tmp.name}):
            app = create_app(mock=True)
        self.assertEqual(app.state.scan_dir, Path(self.tmp.name))

    def test_explicit_scan_dir_wins_over_the_environment(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"NISSAN_SCANNER_SCAN_DIR": "/elsewhere"}):
            app = create_app(mock=True, scan_dir=Path(self.tmp.name))
        self.assertEqual(app.state.scan_dir, Path(self.tmp.name))

    def test_idle_before_any_scan(self) -> None:
        with TestClient(self.app) as client:
            body = client.get("/api/scan").json()
            self.assertEqual(body["state"], "idle")
            self.assertIsNone(body["result"])

    def test_post_runs_scan_saves_file_and_reports_result(self) -> None:
        with TestClient(self.app) as client:
            r = client.post("/api/scan")
            self.assertEqual(r.status_code, 202)
            body = wait_done(client)
            self.assertEqual(body["state"], "done")
            self.assertEqual(body["result"]["summary"]["dtc_cvt"], "hipotese_nao_validada")
            saved = Path(body["file"])
            self.assertTrue(saved.exists())
            self.assertEqual(saved.parent, Path(self.tmp.name))
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["schema"], 1)

    def test_second_post_while_running_is_rejected(self) -> None:
        with TestClient(self.app) as client:
            self.app.state.scan["state"] = "running"
            self.assertEqual(client.post("/api/scan").status_code, 409)

    def test_cross_origin_post_is_refused(self) -> None:
        with TestClient(self.app) as client:
            r = client.post("/api/scan", headers={"Origin": "http://evil.example"})
            self.assertEqual(r.status_code, 403)
            self.assertEqual(client.get("/api/scan").json()["state"], "idle")

    def test_same_origin_post_is_accepted(self) -> None:
        with TestClient(self.app) as client:
            r = client.post("/api/scan", headers={"Origin": "http://testserver"})
            self.assertEqual(r.status_code, 202)
            wait_done(client)

    def test_dtcs_reflect_the_last_scan_and_keep_cvt_unvalidated(self) -> None:
        with TestClient(self.app) as client:
            before = client.get("/api/dtcs").json()
            self.assertFalse(before["performed"])
            client.post("/api/scan")
            wait_done(client)
            after = client.get("/api/dtcs").json()
            self.assertTrue(after["performed"])
            self.assertEqual(after["ecm"]["stored"], [])
            self.assertEqual(after["cvt"]["status"], "hipotese_nao_validada")
            self.assertEqual([c["code"] for c in after["cvt"]["codes"]], ["P0725", "U1000", "P1722"])

    def test_live_stream_resumes_after_scan(self) -> None:
        with TestClient(self.app) as client:
            client.post("/api/scan")
            wait_done(client)
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                f = client.get("/api/params").json()
                if f.get("conn") and not f.get("paused") and f.get("data_available"):
                    break
                time.sleep(0.05)
            else:
                self.fail("live não voltou depois do scan")

    def test_no_clear_or_dtc_scan_routes_exist(self) -> None:
        with TestClient(self.app) as client:
            for path in ("/api/dtcs/scan", "/api/dtcs/clear", "/api/clear", "/api/scan/clear"):
                with self.subTest(path=path):
                    self.assertIn(client.post(path).status_code, (404, 405))


if __name__ == "__main__":
    unittest.main()
