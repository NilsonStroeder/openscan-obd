"""Decoders do car_session.py — dados de logs reais, sem hardware."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import car_session  # noqa: E402

FIELD = ROOT / "tests" / "fixtures" / "lid01_field_20261023.json"


class TestObdDecodePid(unittest.TestCase):
    def test_uses_obd2_formulas(self) -> None:
        self.assertEqual(car_session._obd_decode_pid(0x0C, bytes.fromhex("410c1af8")), 1726.0)
        self.assertEqual(car_session._obd_decode_pid(0x0D, bytes.fromhex("410d32")), 50.0)
        self.assertEqual(car_session._obd_decode_pid(0x11, bytes.fromhex("411136")), 21.2)
        self.assertEqual(car_session._obd_decode_pid(0x05, bytes.fromhex("41057d")), 85.0)

    def test_tolerates_leading_bytes(self) -> None:
        self.assertEqual(car_session._obd_decode_pid(0x0D, bytes.fromhex("00410d32")), 50.0)

    def test_missing_short_or_other_pid_returns_none(self) -> None:
        self.assertIsNone(car_session._obd_decode_pid(0x0C, None))
        self.assertIsNone(car_session._obd_decode_pid(0x0C, bytes.fromhex("410c1a")))
        self.assertIsNone(car_session._obd_decode_pid(0x0C, bytes.fromhex("410d32")))
        self.assertIsNone(car_session._obd_decode_pid(0x0C, bytes.fromhex("7f0112")))


class TestDecodeLid01Live(unittest.TestCase):
    def setUp(self) -> None:
        data = json.loads(FIELD.read_text(encoding="utf-8"))
        self.payloads = {c["label"]: bytes.fromhex(c["hex"]) for c in data["captures"]}
        self.assertTrue(self.payloads)

    def test_only_confirmed_fields_are_named_as_quantities(self) -> None:
        decoded = car_session.decode_lid01_live(next(iter(self.payloads.values())))
        for refuted in ("ATF_TEMP_C", "STM_step", "LOCKUP_b38", "GEAR_b41", "SLIP_b42",
                        "RANGE_b23", "VSP_b11", "VSP_b12"):
            self.assertNotIn(refuted, decoded)
        for confirmed in ("ENG_SPEED_rpm", "VSP_b3", "VSP_b4", "REV_b40"):
            self.assertIn(confirmed, decoded)

    def test_raw_bytes_match_payload(self) -> None:
        for raw in self.payloads.values():
            decoded = car_session.decode_lid01_live(raw)
            self.assertEqual(decoded["b9"], raw[9])
            self.assertEqual(decoded["b30"], raw[30])
            self.assertEqual(decoded["b36_37_word"], (raw[36] << 8) | raw[37])
            self.assertEqual(decoded["b48_67_hex"], raw[48:68].hex())

    def test_reverse_flag_only_on_0x5a(self) -> None:
        for raw in self.payloads.values():
            expected = "REVERSE" if raw[40] == 0x5A else "NOT_REVERSE"
            self.assertEqual(car_session.decode_lid01_live(raw)["REV_b40"], expected)

    def test_short_payload_is_reported(self) -> None:
        self.assertIn("erro", car_session.decode_lid01_live(bytes(68)))


class TestCorrelatedPollTimestamps(unittest.TestCase):
    def test_records_separate_tcm_and_obd_times(self) -> None:
        import tempfile
        import time
        from unittest.mock import patch

        payload = bytes.fromhex(json.loads(FIELD.read_text(encoding="utf-8"))["captures"][0]["hex"])
        obd = {0x0C: "410c1af8", 0x0D: "410d32", 0x11: "411136", 0x05: "41057d"}

        class FakeConn:
            def close(self) -> None:
                pass

        def fake_send_recv(_conn, data, timeout=2.0):
            time.sleep(0.005)
            if data[:1] == b"\x01":
                return bytes.fromhex(obd[data[1]])
            return bytes.fromhex("50c0")

        def fake_read_lid(_conn, _lid, timeout=2.0):
            time.sleep(0.005)
            return payload

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "correlated_test.json"
            with patch.object(car_session, "get_conn", lambda *a, **k: FakeConn()), \
                    patch.object(car_session, "kwp_session", lambda _c: (0xC0, {})), \
                    patch.object(car_session, "send_recv", fake_send_recv), \
                    patch.object(car_session, "kwp_read_lid", fake_read_lid), \
                    patch.object(car_session, "log_path", lambda _tag: out):
                car_session.correlated_poll("fake.dll", duration_s=0.3, interval_s=0.1, label="t")
            data = json.loads(out.read_text(encoding="utf-8"))
            csv_header = out.with_suffix(".csv").read_text(encoding="utf-8").splitlines()[0]

        self.assertIn("started_at", data)
        self.assertGreaterEqual(len(data["records"]), 2)
        for rec in data["records"]:
            self.assertLessEqual(rec["t"], rec["t_tcm"])
            self.assertLess(rec["t_tcm"], rec["t_RPM"])
            for name in ("RPM", "VSP", "TPS", "ECT"):
                self.assertIsNotNone(rec[f"t_{name}"])
            self.assertEqual(rec["obd_VSP"], 50.0)
            self.assertEqual(rec["obd_VSP_raw"], "410d32")
            self.assertEqual(rec["lid01"]["VSP_b3"], payload[3])
        self.assertTrue(csv_header.startswith("t,t_tcm,t_RPM,t_VSP,t_TPS,t_ECT,obd_RPM"))


if __name__ == "__main__":
    unittest.main()
