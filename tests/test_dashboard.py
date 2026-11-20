from html.parser import HTMLParser
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from openscan_obd.api.main import create_app
from openscan_obd.gateway.j2534_mock import J2534DeviceMock


class DashboardMarkupParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tabs = []
        self.panels = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "button" and "data-tab" in attributes:
            self.tabs.append((
                attributes["data-tab"],
                attributes.get("aria-selected"),
            ))
        if tag == "section" and attributes.get("id", "").startswith("panel-"):
            self.panels[attributes["id"]] = "hidden" in attributes


class DashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(mock=True)

    def test_status_identifies_mock_and_disconnected_hardware(self):
        response = TestClient(self.app).get("/api/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "mock")
        self.assertFalse(response.json()["hardware_connected"])

    def test_modules_are_configuration_not_discovery(self):
        response = TestClient(self.app).get("/api/modules")
        body = response.json()
        self.assertEqual(body["data_source"], "configuration_only")
        self.assertEqual(body["modules"][0]["status"], "configured_not_discovered")

    def test_dtc_endpoint_does_not_claim_a_scan(self):
        response = TestClient(self.app).get("/api/dtcs")
        self.assertFalse(response.json()["performed"])
        self.assertIsNone(response.json()["dtcs"])
        self.assertIn("Nenhum scan", response.json()["message"])

    def test_dtc_mutating_or_scanning_routes_are_not_enabled(self):
        client = TestClient(self.app)
        self.assertEqual(client.post("/api/dtcs/scan").status_code, 404)
        self.assertEqual(client.post("/api/dtcs/clear").status_code, 404)

    def test_dashboard_page_is_served(self):
        response = TestClient(self.app).get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Payload LID 0x01", response.text)
        self.assertIn('id="data-status"', response.text)
        self.assertIn("ECM não respondeu ao LID 0x01", response.text)
        self.assertIn("Math.min(1000 * (2 ** reconnectAttempt), 30000)", response.text)
        self.assertIn("tentativa em ${Math.ceil(delayMs / 1000)} s", response.text)

    def test_dashboard_tabs_match_panels_and_default_to_general(self):
        response = TestClient(self.app).get("/")
        parser = DashboardMarkupParser()
        parser.feed(response.text)

        self.assertEqual(
            parser.tabs,
            [("general", "true"), ("cvt", "false"), ("dtc", "false"), ("scan", "false")],
        )
        self.assertEqual(
            parser.panels,
            {"panel-general": False, "panel-cvt": True, "panel-dtc": True, "panel-scan": True},
        )

    def test_dashboard_renders_connection_and_data_failure_states(self):
        response = TestClient(self.app).get("/")
        html = response.text

        self.assertIn("KWP indisponível; tentando recuperar automaticamente.", html)
        self.assertIn("Sessão KWP ativa, mas o ECM não respondeu ao LID 0x01.", html)
        self.assertIn("Resposta LID recebida, mas não pôde ser interpretada:", html)
        self.assertIn(
            "Resposta LID recebida; valores decodificados são hipóteses não validadas.",
            html,
        )
        self.assertIn('setCard("rpm", "rpm", data);', html)
        self.assertIn("reconnectAttempt = 0;", html)

    def test_dashboard_shows_confidence_tier_and_source_per_value(self):
        html = TestClient(self.app).get("/").text
        for text in ("padrão", "confirmado", "estimado", "cru", "indisponível"):
            with self.subTest(tier=text):
                self.assertIn(text, html)
        self.assertIn("age_ms", html)                       # card esmaece quando o dado envelhece
        self.assertIn('id="panel-scan"', html)
        self.assertIn('fetch("/api/scan"', html)
        self.assertIn('method: "POST"', html)
        self.assertIn("leitura ao vivo pausa", html)

    def test_dashboard_never_offers_clearing_dtcs(self):
        html = TestClient(self.app).get("/").text.lower()
        for forbidden in ("/clear", "apagar", "limpar falhas", "limpar dtc", "reset"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html)

    def test_dashboard_has_cvt_cards_for_gear_reverse_atf(self):
        html = TestClient(self.app).get("/").text
        self.assertIn("setCvt(key, data)", html)
        for key in ("gear", "reverse", "atf", "rpm_tcm", "lockup_b38"):
            with self.subTest(key=key):
                self.assertIn(f'id="cvt-{key}"', html)          # o cartão existe
                self.assertIn(f'"{key}"', html)                 # e está na lista que o alimenta

    def test_lifespan_streams_recorded_raw_payload(self):
        with TestClient(self.app) as client:
            status = client.get("/api/status").json()
            response = client.get("/api/params")
            body = response.json()
            self.assertTrue(status["session_active"])
            self.assertEqual(status["mode"], "mock")
            self.assertFalse(status["hardware_connected"])
            self.assertTrue(body["conn"])
            self.assertTrue(body["lid_available"])
            self.assertEqual(body["data_source"], "recorded_fixture")
            self.assertEqual(body["raw_lid01"], "001b0000")
            self.assertTrue(body["data_available"])
            self.assertEqual(body["rpm"], 710.0)          # vem do OBD, não do LID curto
            self.assertEqual(body["schema"], 2)

    def test_long_payload_is_decoded_but_remains_unverified(self):
        payload = bytes([
            0, 68, 0, 0, 128, 128, 65, 0, 250, 148, 45, 128, 128,
        ])
        device = J2534DeviceMock(lid01_payload=payload, obd01={})
        with patch("openscan_obd.api.main._make_device", return_value=device):
            with TestClient(self.app) as client:
                body = client.get("/api/params").json()
        self.assertEqual(body["raw_lid01"], payload.hex())
        self.assertEqual(body["rpm"], 850.0)
        self.assertEqual(body["ect"], 88)
        self.assertFalse(body["verified"])

    def test_websocket_streams_raw_payload_from_mock(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/live") as websocket:
                frame = websocket.receive_json()
        self.assertEqual(frame["data_source"], "recorded_fixture")
        self.assertTrue(frame["conn"])
        self.assertEqual(frame["raw_lid01"], "001b0000")
        self.assertEqual(frame["rpm"], 710.0)

    def test_websocket_broadcast_reaches_multiple_clients(self):
        with TestClient(self.app) as client:
            with client.websocket_connect("/ws/live") as first:
                with client.websocket_connect("/ws/live") as second:
                    frame_one = first.receive_json()
                    frame_two = second.receive_json()
        self.assertEqual(frame_one["raw_lid01"], "001b0000")
        self.assertEqual(frame_two["raw_lid01"], "001b0000")


if __name__ == "__main__":
    unittest.main()


class DashboardNewRowsTests(unittest.TestCase):
    def test_new_obd_values_have_rows_fed_by_their_frame_keys(self) -> None:
        html = TestClient(create_app(mock=True)).get("/").text
        for cid, key in (("ambient", "ambient"), ("lambda", "lambda_cmd"),
                         ("tps-cmd", "tps_cmd"), ("runtime", "runtime")):
            with self.subTest(card=cid):
                self.assertIn(f'id="card-{cid}"', html)
                self.assertIn(f'setCard("{cid}", "{key}", data);', html)
