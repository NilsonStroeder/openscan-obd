"""Perfis de veículo: o que é específico de um carro mora num perfil, não no fluxo genérico."""
from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from openscan_obd.api.main import create_app
from openscan_obd.dids import NISSAN_MODULES
from openscan_obd.gateway.j2534_mock import J2534DeviceMock
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
from openscan_obd.gateway.scan import run_scan
from openscan_obd.profiles import (
    DEFAULT_PROFILE_ID,
    PROFILES,
    UnknownProfile,
    get_profile,
    list_profiles,
)

SENTRA = "nissan-sentra-b16-2010"
GENERIC = "generic-obd2"


class Spy:
    """Registra pares de IDs usados e os pedidos enviados."""
    data_source = "spy"

    def __init__(self) -> None:
        self.inner = J2534DeviceMock()
        self.inner.open()
        self.ids = (0x7E0, 0x7E8)
        self.used_tx: set[int] = set()
        self.sent: list[tuple[int, bytes]] = []

    def set_ids(self, tx: int, rx: int) -> None:
        self.ids = (tx, rx)
        self.inner.set_ids(tx, rx)

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.used_tx.add(self.ids[0])
        self.sent.append((self.ids[0], bytes(data)))
        return self.inner.send_recv(data, timeout_ms=timeout_ms)


class TestRegistry(unittest.TestCase):
    def test_default_is_the_safe_generic_profile(self) -> None:
        self.assertEqual(DEFAULT_PROFILE_ID, GENERIC)

    def test_known_profiles_and_listing(self) -> None:
        self.assertEqual({p.id for p in list_profiles()}, {GENERIC, SENTRA})
        self.assertEqual(get_profile(SENTRA).make, "Nissan")

    def test_unknown_profile_error_lists_the_available_ones(self) -> None:
        with self.assertRaises(UnknownProfile) as ctx:
            get_profile("fusca-1972")
        self.assertIn(GENERIC, str(ctx.exception))
        self.assertIn(SENTRA, str(ctx.exception))

    def test_every_profile_is_well_formed(self) -> None:
        for p in PROFILES.values():
            with self.subTest(profile=p.id):
                self.assertEqual((p.modules["engine"]["tx"], p.modules["engine"]["rx"]), (0x7E0, 0x7E8))
                pairs = [(m["tx"], m["rx"]) for m in p.modules.values()]
                self.assertEqual(len(pairs), len(set(pairs)))
                for m in p.modules.values():
                    self.assertTrue(0 <= m["tx"] <= 0x7FF and 0 <= m["rx"] <= 0x7FF)
                    self.assertIn(m["protocol"], {"obd2", "kwp", "uds"})
                self.assertIn(p.validation, {"generic", "single_vehicle"})
                self.assertTrue(p.description)

    def test_generic_profile_never_touches_manufacturer_modules(self) -> None:
        g = get_profile(GENERIC)
        self.assertEqual(list(g.modules), ["engine"])
        self.assertFalse(g.has_tcm_lid01)
        self.assertEqual(g.validation, "generic")

    def test_sentra_profile_keeps_the_validated_nissan_table(self) -> None:
        s = get_profile(SENTRA)
        self.assertEqual(s.modules, NISSAN_MODULES)
        self.assertTrue(s.has_tcm_lid01)
        self.assertEqual(s.validation, "single_vehicle")
        self.assertIn("B16", s.description)


class TestScanUsesProfile(unittest.TestCase):
    def test_generic_scan_only_talks_to_the_engine_and_skips_tcm(self) -> None:
        spy = Spy()
        res = run_scan(ReadOnlyDevice(spy), profile=get_profile(GENERIC))
        self.assertEqual(spy.used_tx, {0x7E0})
        self.assertEqual(list(res["modules"]), ["engine"])
        self.assertEqual(res["tcm"]["status"], "nao_aplicavel")
        self.assertEqual(res["profile"], GENERIC)
        self.assertNotIn(b"\x10\xc0", [d for _, d in spy.sent])
        self.assertEqual(res["summary"]["dtc_cvt"], "nao_aplicavel")

    def test_sentra_scan_unchanged_and_names_its_profile(self) -> None:
        res = run_scan(ReadOnlyDevice(Spy()), profile=get_profile(SENTRA))
        self.assertEqual(res["profile"], SENTRA)
        self.assertIn("tcm_cvt", res["modules"])
        self.assertEqual(res["tcm"]["status"], "ok")

    def test_scan_without_profile_keeps_the_legacy_sentra_behaviour(self) -> None:
        res = run_scan(ReadOnlyDevice(Spy()))
        self.assertEqual(res["profile"], SENTRA)


class TestAppUsesProfile(unittest.TestCase):
    def test_generic_dashboard_never_polls_the_tcm(self) -> None:
        app = create_app(mock=True, profile=GENERIC)
        with TestClient(app) as client:
            self.assertEqual(client.get("/api/status").json()["vehicle_profile"], GENERIC)
            poller = app.state.poller
            self.assertFalse(poller.tcm_enabled)
            self.assertNotIn(0x7E1, getattr(app.state.device, "used_tx", set()))

    def test_sentra_dashboard_reports_its_profile(self) -> None:
        with TestClient(create_app(mock=True, profile=SENTRA)) as client:
            status = client.get("/api/status").json()
        self.assertEqual(status["vehicle_profile"], SENTRA)
        self.assertTrue(status["tcm_supported"])

    def test_generic_status_says_the_transmission_is_not_read(self) -> None:
        with TestClient(create_app(mock=True, profile=GENERIC)) as client:
            self.assertFalse(client.get("/api/status").json()["tcm_supported"])

    def test_dashboard_page_shows_profile_and_adapts_the_cvt_tab(self) -> None:
        html = TestClient(create_app(mock=True, profile=GENERIC)).get("/").text
        self.assertIn('id="profile-line"', html)
        self.assertIn("no-tcm", html)

    def test_unknown_profile_fails_fast_with_a_clear_message(self) -> None:
        with self.assertRaises(UnknownProfile):
            create_app(mock=True, profile="nao-existe")

    def test_profile_from_environment(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"NISSAN_SCANNER_PROFILE": GENERIC}):
            self.assertEqual(create_app(mock=True).state.profile.id, GENERIC)


if __name__ == "__main__":
    unittest.main()


class TestProfilesCli(unittest.TestCase):
    def test_profiles_command_lists_every_profile_and_marks_the_default(self) -> None:
        from click.testing import CliRunner

        from openscan_obd.cli import main

        res = CliRunner().invoke(main, ["profiles"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertIn("generic-obd2 (padrão)", res.output)
        self.assertIn("nissan-sentra-b16-2010", res.output)
        self.assertIn("single_vehicle", res.output)

    def test_dashboard_rejects_unknown_profile_before_starting(self) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from openscan_obd.cli import main

        with patch("openscan_obd.api.main.main") as run_api:
            res = CliRunner().invoke(main, ["dashboard", "--profile", "fusca-1972"])
        self.assertNotEqual(res.exit_code, 0)
        self.assertIn("generic-obd2", res.output)
        run_api.assert_not_called()
