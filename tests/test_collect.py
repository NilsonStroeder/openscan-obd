"""Coleta ampla só de leitura: descoberta (carro parado) e gravação cíclica (15 min), por trás da guarda."""
from __future__ import annotations

import json
import unittest

from openscan_obd.gateway.collect import plan_from_discovery, run_discovery, run_record
from openscan_obd.gateway.readonly_guard import ALLOWED_SIDS, ReadOnlyDevice

MODULES = {
    "engine": {"tx": 0x7E0, "rx": 0x7E8, "protocol": "obd2", "note": ""},
    "tcm_cvt": {"tx": 0x7E1, "rx": 0x7E9, "protocol": "kwp", "note": ""},
    "eps": {"tx": 0x742, "rx": 0x762, "protocol": "kwp", "note": ""},
    "airbag": {"tx": 0x752, "rx": 0x772, "protocol": "kwp", "note": ""},      # ausente
}


class Bus:
    """Barramento falso: ECM (OBD + KWP), TCM e EPS respondem; o airbag nunca."""
    data_source = "fake"

    def __init__(self, fail_set_ids_times: int = 0) -> None:
        self.ids = (0x7E0, 0x7E8)
        self.sent: list[tuple[tuple[int, int], bytes]] = []
        self.set_calls = 0
        self.resets = 0
        self.fail_set_ids_times = fail_set_ids_times

    def set_ids(self, tx, rx):
        self.set_calls += 1
        if self.fail_set_ids_times > 0:
            self.fail_set_ids_times -= 1
            raise RuntimeError("PassThruStopMsgFilter: ERR_INVALID_MSG")
        self.ids = (tx, rx)

    def reset_channel(self):
        self.resets += 1

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        data = bytes(data)
        self.sent.append((self.ids, data))
        tx = self.ids[0]
        if tx == 0x752:
            raise TimeoutError("ERR_TIMEOUT")
        sid = data[0]
        if tx == 0x7E0 and sid == 0x01:
            pid = data[1]
            if pid == 0x00:
                return bytes.fromhex("410010100000")           # declara os PIDs 04 e 0C
            if pid == 0x04:
                return bytes.fromhex("410480")
            if pid == 0x0C:
                return bytes.fromhex("410c1ae0")
            if pid == 0x52:                                      # responde sem declarar
                return bytes.fromhex("415280")
            raise TimeoutError("ERR_TIMEOUT")
        if sid == 0x09:
            if data[1] == 0x00:
                return bytes.fromhex("490000000000")
            raise TimeoutError("ERR_TIMEOUT")
        if sid == 0x06:
            if data[1] == 0x00:
                return bytes.fromhex("460000000000")
            raise TimeoutError("ERR_TIMEOUT")
        if sid in (0x03, 0x07, 0x0A):
            return bytes([sid + 0x40, 0x00])
        if sid == 0x10:
            return b"\x50\xc0"
        if sid == 0x3E:
            return b"\x7e"
        if sid == 0x1A:
            if data[1] == 0x80:
                return bytes.fromhex("5a80aabb")
            return bytes([0x7F, 0x1A, 0x12])
        if sid == 0x21:
            lids = {0x7E0: {0x01: "6101001b0000", 0x10: "6110315a4a"},
                    0x7E1: {0x01: "610100" + "11" * 66},
                    0x742: {0x01: "6101aa"}}[tx]
            if data[1] in lids:
                return bytes.fromhex(lids[data[1]])
            return bytes([0x7F, 0x21, 0x12])
        raise TimeoutError("ERR_TIMEOUT")


def guarded(bus):
    return ReadOnlyDevice(bus)


class TestDiscovery(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = Bus()
        self.res = run_discovery(guarded(self.bus), MODULES, pid_timeout_ms=10, lid_timeout_ms=10)

    def test_obd_declared_and_undeclared_pids_are_recorded_raw(self) -> None:
        obd = self.res["obd"]
        self.assertEqual(obd["declared_pids"], ["04", "0C"])
        self.assertEqual(obd["declared_raw"]["0C"], "410c1ae0")
        self.assertIn("52", obd["undeclared_responders"])
        self.assertEqual(obd["undeclared_responders"]["52"], "415280")
        self.assertEqual(obd["dtc_raw"]["03"], "4300")

    def test_kwp_modules_report_responding_lids_and_skip_the_absent_one(self) -> None:
        kwp = self.res["kwp"]
        self.assertEqual(sorted(kwp["engine"]["lids"]), ["01", "10"])
        self.assertEqual(sorted(kwp["tcm_cvt"]["lids"]), ["01"])
        self.assertEqual(kwp["eps"]["lids"]["01"], "6101aa")
        self.assertEqual(kwp["airbag"]["status"], "nao_respondeu")
        self.assertEqual(kwp["airbag"]["lids"], {})
        airbag_sends = [d for ids, d in self.bus.sent if ids[0] == 0x752]
        self.assertLess(len(airbag_sends), 6, "módulo ausente não pode receber a varredura inteira")

    def test_ecu_identification_options_are_kept_raw(self) -> None:
        self.assertEqual(self.res["kwp"]["engine"]["ident"]["80"], "5a80aabb")

    def test_only_read_sids_were_sent_and_ids_restored(self) -> None:
        for _ids, data in self.bus.sent:
            self.assertIn(data[0], ALLOWED_SIDS | {0x10})
        self.assertEqual(self.bus.ids, (0x7E0, 0x7E8))

    def test_generic_profile_without_kwp_modules_skips_kwp_entirely(self) -> None:
        bus = Bus()
        res = run_discovery(guarded(bus), {"engine": MODULES["engine"]}, pid_timeout_ms=10, lid_timeout_ms=10)
        self.assertEqual(res["kwp"], {})
        self.assertFalse([d for _i, d in bus.sent if d[0] in (0x10, 0x21, 0x1A)])


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class TestRefusedLidsKeptInPlan(unittest.TestCase):
    def test_lid_refused_with_nrc_other_than_12_enters_plan(self):
        disc = {"obd": {"declared_pids": [], "undeclared_responders": {}},
                "kwp": {"eps": {"status": "respondeu", "tx": "0x742", "rx": "0x762",
                                "lids": {"01": "6101aa"}, "nrc_lids": {"05": "22"}}}}
        plan = plan_from_discovery(disc)
        self.assertEqual(plan["kwp"]["eps"]["lids"], [0x01, 0x05])


class TestPlanAndRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.disc = run_discovery(guarded(Bus()), MODULES, pid_timeout_ms=10, lid_timeout_ms=10)
        self.plan = plan_from_discovery(self.disc)

    def test_plan_includes_declared_and_undeclared_pids_and_only_responding_lids(self) -> None:
        self.assertIn(0x52, self.plan["obd_pids"])
        self.assertEqual(self.plan["kwp"]["tcm_cvt"]["lids"], [0x01])
        self.assertNotIn("airbag", self.plan["kwp"])

    def _run(self, bus, duration=1.0, **kw):
        clock = Clock()
        records: list[dict] = []
        res = run_record(guarded(bus), self.plan, duration, records.append,
                         clock=clock, wall=lambda: 1000.0 + clock.t, sleep=clock.sleep, **kw)
        return res, records

    def test_records_every_source_with_raw_hex_and_stops_at_the_duration(self) -> None:
        res, records = self._run(Bus(), duration=1.0)
        srcs = {r["src"] for r in records if "src" in r}
        self.assertIn("obd:0C", srcs)
        self.assertIn("obd:52", srcs)
        self.assertIn("kwp:tcm_cvt:01", srcs)
        self.assertIn("kwp:eps:01", srcs)
        tcm = next(r for r in records if r.get("src") == "kwp:tcm_cvt:01")
        self.assertTrue(tcm["raw"].startswith("610100"))
        self.assertEqual(records[0]["event"], "coleta_started")
        self.assertEqual(records[-1]["event"], "coleta_finished")
        self.assertGreater(res["cycles"], 1)

    def test_dtc_modes_do_not_share_a_source_name_with_pids_03_07(self) -> None:
        _res, records = self._run(Bus(), duration=1.0)
        srcs = {r["src"] for r in records if "src" in r}
        self.assertTrue({"obd:modo03", "obd:modo07", "obd:modo0A"} <= srcs)
        self.assertNotIn("obd:03", srcs)
        self.assertNotIn("obd:07", srcs)

    def test_slow_modules_are_visited_less_often_than_tcm(self) -> None:
        _res, records = self._run(Bus(), duration=2.0)
        n = lambda s: sum(1 for r in records if r.get("src") == s)
        self.assertGreater(n("kwp:tcm_cvt:01"), n("kwp:eps:01"))

    def test_only_read_sids_even_over_many_cycles(self) -> None:
        bus = Bus()
        self._run(bus, duration=2.0)
        for _ids, data in bus.sent:
            self.assertIn(data[0], ALLOWED_SIDS | {0x10})

    def test_set_ids_failure_triggers_channel_reset_and_the_run_survives(self) -> None:
        bus = Bus(fail_set_ids_times=1)
        res, records = self._run(bus, duration=1.0)
        self.assertGreaterEqual(bus.resets, 1)
        self.assertEqual(records[-1]["event"], "coleta_finished")

    def test_timeouts_are_recorded_not_dropped(self) -> None:
        plan = {"obd_pids": [0x0D], "kwp": {}}      # o barramento falso não responde ao PID 0D
        clock = Clock()
        records: list[dict] = []
        run_record(guarded(Bus()), plan, 0.3, records.append,
                   clock=clock, wall=lambda: clock.t, sleep=clock.sleep)
        self.assertTrue(any(r.get("src") == "obd:0D" and r.get("status") == "timeout" for r in records))

    def test_metadata_goes_into_the_first_record(self) -> None:
        _res, records = self._run(Bus(), duration=0.3, meta={"fuel": "etanol", "vehicle": "teste"})
        self.assertEqual(records[0]["meta"]["fuel"], "etanol")

    def test_keyboard_interrupt_ends_with_a_finished_event(self) -> None:
        class Ctrl(Bus):
            def send_recv(self, data, timeout_ms=200):
                if len(self.sent) > 40:
                    raise KeyboardInterrupt
                return super().send_recv(data, timeout_ms)
        _res, records = self._run(Ctrl(), duration=60.0)
        self.assertEqual(records[-1]["event"], "coleta_finished")
        self.assertTrue(records[-1]["summary"]["interrupted"])


if __name__ == "__main__":
    unittest.main()


class TestPlanoRapido(unittest.TestCase):
    PLANO = {"obd_pids": [0x04, 0x05, 0x0C, 0x0D], "kwp": {"tcm_cvt": {"tx": 0x7E1, "rx": 0x7E9, "lids": [1], "dids": []}}}

    def test_so_obd_remove_os_modulos_kwp(self) -> None:
        from openscan_obd.gateway.collect import plano_rapido
        p = plano_rapido(self.PLANO, so_obd=True)
        self.assertEqual(p["kwp"], {})
        self.assertEqual(p["obd_pids"], self.PLANO["obd_pids"])
        self.assertIn("tcm_cvt", self.PLANO["kwp"])            # não altera o original

    def test_lista_de_pids_filtra_e_ignora_os_que_nao_estao_no_plano(self) -> None:
        from openscan_obd.gateway.collect import plano_rapido
        p = plano_rapido(self.PLANO, pids="0C,0D,99")
        self.assertEqual(p["obd_pids"], [0x0C, 0x0D])
        self.assertIn("tcm_cvt", p["kwp"])
