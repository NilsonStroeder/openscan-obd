from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import Browser, Playwright, WebSocketRoute, sync_playwright

from openscan_obd.gateway.capture_visualization import (
    generate_capture_comparison_report,
)

ROOT = Path(__file__).resolve().parents[2]


class BrowserInteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._server_temp_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._cleanup)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            cls.port = listener.getsockname()[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        env = os.environ.copy()
        source_path = str(ROOT / "src")
        env["PYTHONPATH"] = os.pathsep.join(
            filter(None, [source_path, env.get("PYTHONPATH")])
        )
        env["NISSAN_SCANNER_SCAN_DIR"] = cls._server_temp_dir.name   # scan não suja logs/
        env["NISSAN_SCANNER_PROFILE"] = "nissan-sentra-b16-2010"      # câmbio CVT precisa do perfil do carro de teste
        cls.server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openscan_obd.cli",
                "dashboard",
                "--host",
                "127.0.0.1",
                "--port",
                str(cls.port),
                "--mock",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        cls._wait_for_server()

        cls.playwright: Playwright = sync_playwright().start()
        cls.browser: Browser = cls.playwright.chromium.launch()

    @classmethod
    def _cleanup(cls) -> None:
        if hasattr(cls, "browser"):
            cls.browser.close()
        if hasattr(cls, "playwright"):
            cls.playwright.stop()
        if hasattr(cls, "server"):
            if cls.server.poll() is None:
                cls.server.terminate()
                try:
                    cls.server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    cls.server.kill()
                    cls.server.wait(timeout=10)
        if hasattr(cls, "_server_temp_dir"):
            cls._server_temp_dir.cleanup()

    @classmethod
    def _wait_for_server(cls) -> None:
        deadline = time.monotonic() + 30
        status_url = f"{cls.base_url}/api/status"
        while time.monotonic() < deadline:
            if cls.server.poll() is not None:
                raise RuntimeError(
                    f"Dashboard server exited early with code {cls.server.returncode}"
                )
            try:
                with urlopen(status_url, timeout=1) as response:
                    if response.status == 200:
                        return
            except (OSError, URLError):
                time.sleep(0.2)
        raise TimeoutError(f"Dashboard did not start at {status_url}")

    def setUp(self) -> None:
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)

    def test_dashboard_mock_stream_and_tab_navigation(self) -> None:
        self.page.goto(self.base_url)

        self.page.get_by_role("status").filter(
            has_text="Mock offline · fixture gravada"
        ).wait_for()
        self.assertNotEqual(
            self.page.locator("#raw-payload").inner_text(), "indisponível",
        )
        self.assertTrue(self.page.locator("#panel-general").is_visible())

        self.page.get_by_role("button", name="CVT").click()
        self.assertTrue(self.page.locator("#panel-cvt").is_visible())
        self.assertEqual(
            self.page.get_by_role("button", name="CVT").get_attribute("aria-selected"),
            "true",
        )

        self.page.get_by_role("button", name="DTCs").click()
        self.assertTrue(self.page.locator("#panel-dtc").is_visible())
        self.assertIn(
            "Nenhum scan executado",
            self.page.locator("#dtc-result").inner_text(),
        )

        self.page.get_by_role("button", name="Geral").click()
        self.assertTrue(self.page.locator("#panel-general").is_visible())

    def test_general_cards_show_obd_values_with_standard_badge(self) -> None:
        self.page.goto(self.base_url)
        self.page.locator("#tier-rpm").get_by_text("padrão").wait_for()
        self.assertEqual(self.page.locator("#rpm").inner_text(), "710")
        self.assertEqual(self.page.locator("#coolant").inner_text(), "94")
        self.assertIn("obd:0C", self.page.locator("#why-rpm").inner_text())
        # sem fonte no ECM do B16: aparece o motivo, nunca um número inventado
        self.assertEqual(self.page.locator("#inj-pw").inner_text(), "—")
        self.assertIn("Sem PID padrão", self.page.locator("#why-inj-pw").inner_text())
        self.assertIn("OBD-II", self.page.locator("#data-status").inner_text())

    def test_header_shows_the_active_vehicle_profile(self) -> None:
        page = self.browser.new_page()
        page.goto(self.base_url)
        page.wait_for_function("document.getElementById('profile-line').textContent.includes('sentra')")
        self.assertEqual(page.locator("#profile-line").inner_text(), "Perfil: nissan-sentra-b16-2010")
        page.close()

    def test_cvt_tab_shows_gear_confirmed_and_atf_estimated(self) -> None:
        self.page.goto(self.base_url)
        self.page.get_by_role("button", name="CVT").click()
        self.page.locator("#tier-cvt-gear").get_by_text("confirmado").wait_for()
        self.assertEqual(self.page.locator("#cvt-gear-value").inner_text(), "P")
        self.assertEqual(self.page.locator("#cvt-reverse-value").inner_text(), "Não")
        self.assertEqual(self.page.locator("#tier-cvt-atf").inner_text(), "estimado")
        self.assertEqual(self.page.locator("#tier-cvt-lockup_b38").inner_text(), "cru")

    def test_tach_bar_follows_rpm_and_gear_gate_lights_the_current_position(self) -> None:
        self.page.goto(self.base_url)
        self.page.locator("#tier-rpm").get_by_text("padrão").wait_for()
        largura = self.page.locator("#tach-fill").evaluate("e => e.style.width")
        self.assertTrue(0 < float(largura.rstrip("%")) < 20, largura)   # 710 rpm de 7000
        self.page.get_by_role("button", name="CVT").click()
        self.page.locator("#tier-cvt-gear").get_by_text("confirmado").wait_for()
        aceso = self.page.locator('#gate span[aria-current="true"]')
        self.assertEqual(aceso.count(), 1)
        self.assertEqual(aceso.inner_text(), "P")

    def test_scan_tab_runs_scan_and_never_claims_clean_cvt(self) -> None:
        self.page.goto(self.base_url)
        self.page.get_by_role("button", name="Scan", exact=True).click()
        self.page.get_by_role("button", name="Iniciar scan").click()
        self.page.locator("#scan-status").get_by_text("Scan concluído.").wait_for()
        summary = self.page.locator("#scan-summary").inner_text()
        self.assertIn("não suportado por este ECM", summary)        # VIN
        self.assertIn("hipótese, não validada: P0725, U1000, P1722", summary)   # CVT
        self.assertIn("scan_", summary)                             # arquivo salvo
        self.page.get_by_role("button", name="DTCs").click()
        text = self.page.locator("#dtc-result").inner_text()
        self.assertIn("confirmados: nenhum", text)
        self.assertIn("HIPÓTESE, não validada: P0725, U1000, P1722", text)
        self.assertNotIn("sem falhas", text)
        self.assertEqual(self.page.get_by_role("button", name="Limpar").count(), 0)

    def test_paused_frame_shows_banner_and_dims_nothing_else(self) -> None:
        def route_websocket(websocket_route: WebSocketRoute) -> None:
            websocket_route.send(json.dumps({
                "schema": 2, "conn": True, "paused": True, "data_available": False,
                "data_source": "browser_test", "values": {}, "cvt": {},
                "message": "Scan em andamento: leitura ao vivo pausada.",
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#paused-banner").wait_for(state="visible")
        self.assertIn("pausada", self.page.locator("#data-status").inner_text())

    def test_lambda_always_shows_two_decimals_and_fuel_trims_one(self) -> None:
        def route_websocket(websocket_route: WebSocketRoute) -> None:
            def item(value: float, unit: str, source: str) -> dict:
                return {"value": value, "unit": unit, "source": source, "tier": "padrao",
                        "age_ms": 120, "stale_ms": 2000, "raw": "00"}
            websocket_route.send(json.dumps({
                "schema": 2, "conn": True, "data_available": True,
                "data_source": "browser_test", "cvt": {},
                "values": {"lambda_cmd": item(1.0, "λ", "obd:44"),
                           "ltft": item(20.3125, "%", "obd:07"),
                           "stft": item(0.0, "%", "obd:06")},
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#tier-lambda").get_by_text("padrão").wait_for()
        self.assertEqual(self.page.locator("#lambda").inner_text(), "1.00")
        self.assertEqual(self.page.locator("#ltft").inner_text(), "20.3")
        self.assertEqual(self.page.locator("#stft").inner_text(), "0.0")

    def test_slow_value_between_visits_is_not_dimmed_and_rpm_is_whole(self) -> None:
        def route_websocket(websocket_route: WebSocketRoute) -> None:
            websocket_route.send(json.dumps({
                "schema": 2, "conn": True, "data_available": True,
                "data_source": "browser_test", "cvt": {},
                "values": {
                    "rpm": {"value": 1193.75, "unit": "rpm", "source": "obd:0C", "tier": "padrao",
                            "age_ms": 120, "stale_ms": 2000, "raw": "410c12a8"},
                    "iat": {"value": 34, "unit": "C", "source": "obd:0F", "tier": "padrao",
                            "age_ms": 6200, "stale_ms": 15000, "raw": "410f4e"}},
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#tier-iat").get_by_text("padrão").wait_for()
        self.assertEqual(self.page.locator("#rpm").inner_text(), "1194")
        self.assertNotIn("stale", self.page.locator("#card-iat").get_attribute("class"))

    def test_card_heights_do_not_change_when_a_value_loses_its_source_line(self) -> None:
        self.page.goto(self.base_url)
        self.page.locator("#tier-rpm").get_by_text("padrão").wait_for()
        com = self.page.locator("#card-speed").bounding_box()["height"]
        self.page.evaluate("document.getElementById('why-speed').textContent = ''")
        sem = self.page.locator("#card-speed").bounding_box()["height"]
        self.assertEqual(com, sem)

    def test_stale_value_is_dimmed_and_says_how_old(self) -> None:
        def route_websocket(websocket_route: WebSocketRoute) -> None:
            websocket_route.send(json.dumps({
                "schema": 2, "conn": True, "data_available": True,
                "data_source": "browser_test", "cvt": {},
                "values": {"rpm": {"value": 710, "unit": "rpm", "source": "obd:0C",
                                   "tier": "padrao", "age_ms": 6200, "raw": "410c0b18"}},
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#card-rpm.stale").wait_for()
        self.assertIn("6.2 s", self.page.locator("#why-rpm").inner_text())

    def test_dashboard_shows_failure_and_recovers(self) -> None:
        websocket_routes: list[WebSocketRoute] = []

        def route_websocket(websocket_route: WebSocketRoute) -> None:
            websocket_routes.append(websocket_route)
            websocket_route.send(json.dumps({
                "conn": False,
                "lid_available": False,
                "data_source": "browser_test",
                "error": "browser-test transient timeout",
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#data-status").get_by_text(
            "browser-test transient timeout"
        ).wait_for()
        self.assertEqual(
            self.page.locator("#connection").get_attribute("data-state"),
            "error",
        )

        self.assertTrue(websocket_routes)
        websocket_routes[0].send(json.dumps({
            "conn": True,
            "lid_available": True,
            "data_source": "browser_test",
            "raw_lid01": "001b0000",
            "verified": False,
            "rpm": 850,
            "ts": time.time(),
        }))
        self.page.locator("#data-status").get_by_text(
            "valores decodificados são hipóteses não validadas"
        ).wait_for()
        self.assertEqual(
            self.page.locator("#connection").get_attribute("data-state"),
            "connected",
        )
        self.assertEqual(self.page.locator("#raw-payload").inner_text(), "001b0000")

    def test_dashboard_shows_lid_nrc(self) -> None:
        def route_websocket(websocket_route: WebSocketRoute) -> None:
            websocket_route.send(json.dumps({
                "conn": True,
                "lid_available": False,
                "raw_lid01": None,
                "lid_response": "negative",
                "lid_nrc": "12",
                "raw_lid_response": "7f2112",
                "data_source": "browser_test",
                "ts": time.time(),
            }))

        self.page.route_web_socket("**/ws/live", route_websocket)
        self.page.goto(self.base_url)
        self.page.locator("#data-status").get_by_text(
            "o ECM recusou o LID 0x01 (NRC 0x12)"
        ).wait_for()

    def test_comparison_warning_and_signal_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.jsonl"
            second = Path(temp_dir) / "second.jsonl"
            report = Path(temp_dir) / "comparison.html"
            self._write_capture(first, "Sentra B16", "profile_a", rpm=700)
            self._write_capture(second, "Outro veículo", "profile_b", rpm=800)
            generate_capture_comparison_report(first, second, report)

            self.page.goto(report.as_uri())
            self.page.locator("#warnings").get_by_text(
                "Atenção: diferenças detectadas"
            ).wait_for()
            self.assertIn(
                "perfil do decoder",
                self.page.locator("#warnings").inner_text(),
            )
            self.assertTrue(self.page.locator("#chart-rpm").is_visible())
            self.page.get_by_role("checkbox", name="RPM (hipótese)").uncheck()
            self.assertFalse(self.page.locator("#chart-rpm").is_visible())
            self.page.get_by_role("checkbox", name="RPM (hipótese)").check()
            self.assertTrue(self.page.locator("#chart-rpm").is_visible())

    def test_comparison_shows_empty_state_without_common_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.jsonl"
            second = Path(temp_dir) / "second.jsonl"
            report = Path(temp_dir) / "comparison-empty.html"
            self._write_capture(first, "Sentra B16", "profile_a", rpm=700)
            self._write_capture(second, "Sentra B16", "profile_a", vsp=12)
            generate_capture_comparison_report(first, second, report)

            self.page.goto(report.as_uri())
            self.page.get_by_text(
                "Não há sinais numéricos em comum nas duas capturas para comparar."
            ).wait_for()
            self.assertEqual(self.page.locator("#charts").inner_text(), "")

    @staticmethod
    def _write_capture(
        path: Path,
        vehicle: str,
        profile: str,
        **values: float,
    ) -> None:
        start = datetime.now(timezone.utc)
        metadata = {
            "vehicle": vehicle,
            "ecu": "ECM",
            "vehicle_profile": "browser_test_profile",
            "adapter": "mock",
            "validation_status": "not_validated",
        }
        records: list[dict[str, Any]] = [{
            "event": "capture_started",
            "schema_version": 1,
            "captured_at": start.isoformat(),
            "metadata": metadata,
        }]
        for index in range(2):
            timestamp = start.timestamp() + index
            frame_values = {key: value + index for key, value in values.items()}
            records.append({
                "event": "frame",
                "captured_at": datetime.fromtimestamp(
                    timestamp, tz=timezone.utc
                ).isoformat(),
                "frame": {
                    "ts": timestamp,
                    "conn": True,
                    "lid_available": True,
                    "profile": profile,
                    "verified": False,
                    **frame_values,
                },
            })
        records.append({
            "event": "capture_stopped",
            "captured_at": datetime.fromtimestamp(
                start.timestamp() + 2, tz=timezone.utc
            ).isoformat(),
        })
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
