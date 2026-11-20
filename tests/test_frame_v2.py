"""Frame v2 do dashboard e agendador de PIDs OBD: lógica pura, sem hardware."""
from __future__ import annotations

import unittest

from openscan_obd.gateway import frame_v2 as f2
from openscan_obd.gateway.poller import read_obd_live

FAST = {0x0C: "rpm", 0x0D: "vsp"}
SLOW = {0x05: "ect", 0x0F: "iat", 0x42: "vbat"}


class TestObdSchedule(unittest.TestCase):
    def test_fast_every_batch_and_slow_round_robin(self) -> None:
        sch = f2.ObdSchedule(FAST, SLOW)
        slow_seen = []
        for _ in range(6):
            batch = sch.next_batch()
            self.assertTrue(set(FAST) <= set(batch))
            slow_seen.append(next(p for p in batch if p in SLOW))
        self.assertEqual(slow_seen, [0x05, 0x0F, 0x42, 0x05, 0x0F, 0x42])

    def test_negative_response_drops_pid_for_good(self) -> None:
        sch = f2.ObdSchedule(FAST, SLOW)
        sch.record(0x0F, {"nrc": "11"})
        seen = {p for _ in range(6) for p in sch.next_batch()}
        self.assertNotIn(0x0F, seen)
        self.assertEqual(sch.unsupported, {0x0F})

    def test_timeouts_drop_pid_only_after_three_in_a_row(self) -> None:
        sch = f2.ObdSchedule(FAST, SLOW)
        sch.record(0x05, {"error": "sem resposta"})
        sch.record(0x05, {"error": "sem resposta"})
        self.assertNotIn(0x05, sch.unsupported)
        sch.record(0x05, {"value": 90.0})            # sucesso zera a contagem
        sch.record(0x05, {"error": "sem resposta"})
        sch.record(0x05, {"error": "sem resposta"})
        self.assertNotIn(0x05, sch.unsupported)
        sch.record(0x05, {"error": "sem resposta"})
        self.assertIn(0x05, sch.unsupported)

    def test_all_slow_unsupported_still_returns_fast(self) -> None:
        sch = f2.ObdSchedule(FAST, SLOW)
        for pid in SLOW:
            sch.record(pid, {"nrc": "11"})
        self.assertEqual(set(sch.next_batch()), set(FAST))


class TestTcmCache(unittest.TestCase):
    def decoded(self, **changes):
        from openscan_obd.gateway.tcm_lid01 import decode_tcm_lid01
        from pathlib import Path
        base = bytearray(bytes.fromhex(
            (Path(__file__).parent / "fixtures" / "tcm_lid01_raw.hex").read_text().strip()))
        for k, v in changes.items():
            base[int(k[1:])] = v
        return decode_tcm_lid01(bytes(base))

    def test_tiers_per_field(self) -> None:
        cache = {}
        f2.update_tcm_cache(cache, self.decoded(b54=0x80, b40=0x5A), t=5.0)
        self.assertEqual(cache["gear"]["value"], "D")
        self.assertEqual(cache["gear"]["tier"], "confirmado")
        self.assertEqual(cache["gear"]["source"], "tcm:21 01[54]>>4")
        self.assertIs(cache["reverse"]["value"], True)
        self.assertEqual(cache["reverse"]["tier"], "confirmado")
        self.assertEqual(cache["atf"]["tier"], "estimado")
        self.assertEqual(cache["atf"]["unit"], "C")
        self.assertEqual(cache["lockup_b38"]["tier"], "cru")
        self.assertEqual(cache["lockup_b38"]["raw"], cache["lockup_b38"]["value"])

    def test_rpm_and_speed_from_tcm_are_confirmed(self) -> None:
        cache = {}
        f2.update_tcm_cache(cache, self.decoded(b6=0x0B, b7=0x18, b3=7, b4=7), t=1.0)
        self.assertEqual((cache["rpm_tcm"]["value"], cache["rpm_tcm"]["tier"]), (355.0, "confirmado"))
        self.assertEqual(cache["vsp_tcm"]["value"], 7)

    def test_unknown_gear_is_kept_raw_not_invented(self) -> None:
        cache = {}
        f2.update_tcm_cache(cache, self.decoded(b54=0x9F), t=1.0)
        self.assertIsNone(cache["gear"]["value"])
        self.assertEqual(cache["gear"]["tier"], "cru")
        self.assertEqual(cache["gear"]["raw"], "0x9F")


class TestFrameBuilding(unittest.TestCase):
    def obd_result(self):
        class Dev:
            def send_recv(self, data, timeout_ms=200):
                return {0x0C: bytes.fromhex("410c0b18"), 0x0D: bytes.fromhex("410d00")}[data[1]]
        return read_obd_live(Dev(), FAST)

    def test_obd_cache_entries_carry_source_tier_and_raw(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, self.obd_result(), FAST, t=10.0)
        e = cache["rpm"]
        self.assertEqual((e["value"], e["unit"]), (710.0, "rpm"))
        self.assertEqual((e["source"], e["tier"], e["raw"]), ("obd:0C", "padrao", "410c0b18"))

    def test_render_adds_age_and_drops_internal_time(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, self.obd_result(), FAST, t=10.0)
        out = f2.render_values(cache, now=10.25)
        self.assertEqual(out["rpm"]["age_ms"], 250)
        self.assertNotIn("t", out["rpm"])
        self.assertIn("t", cache["rpm"])                 # o cache não é mutado

    def test_failed_pid_is_reported_unavailable_with_reason(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, {"pids": {"rpm": {"nrc": "11"}}, "raw": {}}, {0x0C: "rpm"}, t=1.0)
        self.assertEqual(cache["rpm"]["tier"], "indisponivel")
        self.assertIsNone(cache["rpm"]["value"])
        self.assertIn("NRC 0x11", cache["rpm"]["reason"])

    def test_module_state_ok_stale_unavailable(self) -> None:
        self.assertEqual(f2.module_state(10.0, now=10.5)["status"], "ok")
        self.assertEqual(f2.module_state(10.0, now=15.0)["status"], "stale")
        self.assertEqual(f2.module_state(None, now=15.0)["status"], "unavailable")
        self.assertEqual(f2.module_state(10.0, now=10.1, error="boom")["error"], "boom")

    def test_frame_keeps_legacy_flat_keys_and_marks_data_available(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, self.obd_result(), FAST, t=10.0)
        frame = f2.build_frame(ts=123.0, conn=True, data_source="j2534", values=cache, cvt={},
                               modules={"ecm": f2.module_state(10.0, now=10.1)}, now=10.1)
        self.assertEqual(frame["schema"], 2)
        self.assertEqual(frame["rpm"], 710.0)
        self.assertEqual(frame["vsp"], 0)
        self.assertTrue(frame["data_available"])
        self.assertIs(frame["verified"], True)
        self.assertEqual(frame["values"]["rpm"]["source"], "obd:0C")

    def test_frame_without_values_is_not_available(self) -> None:
        frame = f2.build_frame(ts=1.0, conn=True, data_source="j2534", values={}, cvt={},
                               modules={}, now=1.0)
        self.assertFalse(frame["data_available"])
        self.assertNotIn("rpm", frame)

    def test_failed_connection_cycle_does_not_publish_flat_values(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, self.obd_result(), FAST, t=10.0)
        frame = f2.build_frame(ts=1.0, conn=False, data_source="j2534", values=cache, cvt={},
                               modules={}, now=10.1)
        self.assertNotIn("rpm", frame)
        self.assertFalse(frame["data_available"])
        self.assertIn("rpm", frame["values"])            # histórico continua visível, com idade

    def test_slow_pid_stays_fresh_between_its_round_robin_visits(self) -> None:
        # Bug real: PID lento (visitado a cada ~14 ciclos) passava de 2 s e piscava/sumia.
        cache: dict = {}
        res = {"pids": {"iat": {"value": 34, "unit": "C", "name": "x"},
                        "rpm": {"value": 1190, "unit": "rpm", "name": "x"}}, "raw": {}}
        f2.update_obd_cache(cache, res, {0x0F: "iat", 0x0C: "rpm"}, 100.0,
                                  slow_pids={0x0F})
        out = f2.build_frame(ts=1.0, conn=True, data_source="t", values=cache, cvt={},
                                   modules={}, now=106.0)        # 6 s depois
        self.assertEqual(out["values"]["iat"]["stale_ms"], int(f2.SLOW_STALE_AFTER_S * 1000))
        self.assertEqual(out["values"]["rpm"]["stale_ms"], int(f2.STALE_AFTER_S * 1000))
        self.assertEqual(out["iat"], 34)                        # lento ainda vale
        self.assertNotIn("rpm", out)                            # rápido de 6 s já não vale

    def test_stale_values_do_not_feed_legacy_keys(self) -> None:
        cache = {}
        f2.update_obd_cache(cache, self.obd_result(), FAST, t=10.0)
        frame = f2.build_frame(ts=1.0, conn=True, data_source="j2534", values=cache, cvt={},
                               modules={}, now=20.0)
        self.assertNotIn("rpm", frame)                   # 10 s sem atualizar: não mostra como atual
        self.assertEqual(frame["values"]["rpm"]["age_ms"], 10000)


if __name__ == "__main__":
    unittest.main()
