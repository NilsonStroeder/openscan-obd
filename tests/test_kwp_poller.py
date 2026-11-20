"""Poller KWP em thread — usa mock e asyncio.Queue, sem FastAPI."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.j2534_mock import J2534DeviceMock  # noqa: E402
from openscan_obd.gateway.kwp_session import KWPSession  # noqa: E402
from openscan_obd.gateway.poller import KWPPoller  # noqa: E402


class OneShotTimeoutDevice:
    data_source = "test_mock"

    def __init__(self) -> None:
        self.device = J2534DeviceMock()
        self.fail_session_once = True

    def open(self) -> None:
        self.device.open()

    def close(self) -> None:
        self.device.close()

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        if data[:1] == b"\x10" and self.fail_session_once:
            self.fail_session_once = False
            raise TimeoutError("transient session timeout")
        return self.device.send_recv(data, timeout_ms)


class TestKWPPoller(unittest.IsolatedAsyncioTestCase):
    async def test_retries_after_transient_session_failure(self) -> None:
        device = OneShotTimeoutDevice()
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(
            session, queue, asyncio.get_running_loop(),
            interval_s=0.01, keepalive_s=1.0,
        )
        poller.start()
        try:
            failed = await asyncio.wait_for(queue.get(), timeout=1.0)
            recovered = await asyncio.wait_for(queue.get(), timeout=3.0)
        finally:
            poller.stop()
            device.close()
        self.assertFalse(failed["conn"])
        self.assertIn("transient session timeout", failed["error"])
        self.assertTrue(recovered["conn"])
        self.assertEqual(recovered["raw_lid01"], "001b0000")

    async def test_publishes_conn_and_ts_without_crashing_on_short_lid(self) -> None:
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(
            session, queue, asyncio.get_running_loop(),
            interval_s=0.02, keepalive_s=0.05,
        )
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        self.assertIn("ts", frame)
        self.assertIn("conn", frame)
        self.assertTrue(frame["conn"])
        self.assertEqual(frame["raw_lid01"], "001b0000")
        self.assertEqual(frame["data_source"], "recorded_fixture")

    async def test_frame_v2_has_obd_values_even_with_short_ecm_lid(self) -> None:
        # Causa raiz de 2026-11-15: LID 0x01 do ECM tem 4 bytes, mas OBD modo 01 responde.
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        self.assertEqual(frame["schema"], 2)
        self.assertTrue(frame["lid_available"])          # LID do ECM positivo (4 bytes)
        self.assertIn("decode_error", frame)             # ...mas curto demais para o perfil B17
        self.assertTrue(frame["data_available"])         # o dado vem do OBD
        self.assertEqual(frame["rpm"], 710.0)
        self.assertEqual(frame["values"]["rpm"]["source"], "obd:0C")
        self.assertEqual(frame["values"]["rpm"]["tier"], "padrao")
        self.assertEqual(frame["modules"]["ecm"]["status"], "ok")

    async def test_tcm_read_fills_cvt_and_restores_ecm_ids(self) -> None:
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
        self.assertEqual(frame["cvt"]["gear"]["value"], "P")
        self.assertEqual(frame["cvt"]["gear"]["tier"], "confirmado")
        self.assertEqual(frame["modules"]["tcm"]["status"], "ok")
        self.assertEqual((mock._tx, mock._rx), (0x7E0, 0x7E8))   # volta ao ECM
        mock.close()

    async def test_frame_carries_raw_tcm_lid01_hex_of_full_positive_response(self) -> None:
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        raw = frame["raw_tcm_lid01"]
        self.assertIsInstance(raw, str)
        self.assertEqual(raw, raw.lower())
        self.assertTrue(raw.startswith("6101"))
        self.assertEqual(len(raw), 2 * (1 + 69))          # 61 + 69 bytes (LID incluso)

    async def test_raw_tcm_lid01_is_none_when_tcm_does_not_answer(self) -> None:
        device = OneShotTimeoutDevice()                    # sem set_ids: TCM indisponível
        device.fail_session_once = False
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            device.close()
        self.assertIn("raw_tcm_lid01", frame)
        self.assertIsNone(frame["raw_tcm_lid01"])

    async def test_raw_tcm_lid01_is_none_when_profile_has_no_tcm(self) -> None:
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0, tcm_enabled=False)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        self.assertIn("raw_tcm_lid01", frame)
        self.assertIsNone(frame["raw_tcm_lid01"])

    async def test_device_without_set_ids_leaves_tcm_unavailable(self) -> None:
        device = OneShotTimeoutDevice()
        device.fail_session_once = False
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            device.close()
        self.assertTrue(frame["conn"])
        self.assertEqual(frame["modules"]["tcm"]["status"], "unavailable")
        self.assertEqual(frame["cvt"], {})
        self.assertTrue(frame["data_available"])         # OBD segue funcionando

    async def test_poller_requests_every_pid_the_real_ecm_declares_and_we_decode(self) -> None:
        # bitmap real: 03 04 05 06 07 0C 0D 0E 0F 10 11 13 14 15 1C 1F 20 | 2E 30 31 | 42 43 44 45 46 47 4C
        from openscan_obd.gateway.poller import OBD_FAST_PIDS, OBD_SLOW_PIDS
        from openscan_obd.obd2 import PID_TABLE
        declared = {0x04, 0x05, 0x06, 0x07, 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11, 0x14, 0x15,
                    0x1F, 0x42, 0x43, 0x44, 0x46, 0x4C}
        requested = set(OBD_FAST_PIDS) | set(OBD_SLOW_PIDS)
        self.assertEqual(declared - requested, set())
        self.assertEqual(requested - declared, set())
        self.assertLessEqual(requested, set(PID_TABLE))

    def test_read_obd_live_rejects_a_reply_that_answers_another_pid(self) -> None:
        # defesa em profundidade: mesmo que a camada do adaptador deixe passar
        class Cruzado:
            def send_recv(self, data, timeout_ms=200):
                return bytes.fromhex("410c12a8")            # sempre RPM, qualquer que seja o pedido
        from openscan_obd.gateway.poller import read_obd_live
        res = read_obd_live(Cruzado(), {0x0C: "rpm", 0x0D: "vsp"})
        self.assertEqual(res["rpm"], 1194.0)
        self.assertNotIn("vsp", res)
        self.assertIn("outro PID", res["pids"]["vsp"]["error"])

    async def test_default_reads_tcm_every_cycle_so_obd_and_tcm_are_in_the_same_frame(self) -> None:
        # Carro 2026-11-16: com tcm_every=3 o skew mediano era -300..-380 ms (critério ≤ 100 ms).
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.01, keepalive_s=1.0)
        self.assertEqual(poller.tcm_every, 1)
        poller.start()
        try:
            frames = [await asyncio.wait_for(queue.get(), timeout=2.0) for _ in range(6)]
        finally:
            poller.stop()
            mock.close()
        skews = [abs(f["timing"]["tcm_obd_skew_ms"]) for f in frames[2:]
                 if f["timing"]["tcm_obd_skew_ms"] is not None]
        self.assertTrue(skews)
        self.assertLessEqual(max(skews), 100.0)

    async def test_frame_records_latencies_for_the_capture(self) -> None:
        # F2: ciclo ≤ 500 ms e troca de módulo precisam ser medidos e gravados na captura.
        mock = J2534DeviceMock()
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        t = frame["timing"]
        for key in ("cycle_ms", "obd_ms", "tcm_ms"):
            with self.subTest(key=key):
                self.assertIsInstance(t[key], (int, float))
                self.assertGreaterEqual(t[key], 0)
        self.assertGreaterEqual(t["cycle_ms"], t["obd_ms"])
        self.assertIn("tcm_obd_skew_ms", t)             # defasagem TCM↔OBD (critério ≤ 100 ms)

    async def test_obd_refused_by_ecm_is_reported_not_hidden(self) -> None:
        class NoObd(OneShotTimeoutDevice):
            def send_recv(self, data, timeout_ms=200):
                if data[:1] == b"\x01":
                    return bytes([0x7F, 0x01, 0x11])
                return super().send_recv(data, timeout_ms)

        device = NoObd()
        device.fail_session_once = False
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            device.close()
        self.assertFalse(frame["data_available"])
        self.assertEqual(frame["values"]["rpm"]["tier"], "indisponivel")
        self.assertIn("NRC 0x11", frame["values"]["rpm"]["reason"])

    async def test_decodes_when_payload_meets_minimum(self) -> None:
        payload = bytes([0x00, 68, 0x00, 0x00, 128, 128, 65, 0x00, 250, 148, 45, 128, 128])
        mock = J2534DeviceMock(lid01_payload=payload, obd01={})   # sem OBD: cai no perfil B17
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(
            session, queue, asyncio.get_running_loop(),
            interval_s=0.02, keepalive_s=1.0,
        )
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        self.assertTrue(frame["conn"])
        self.assertEqual(frame["rpm"], 850.0)

    async def test_obd_wins_over_unverified_b17_profile(self) -> None:
        payload = bytes([0x00, 68, 0x00, 0x00, 128, 128, 65, 0x00, 250, 148, 45, 128, 128])
        mock = J2534DeviceMock(lid01_payload=payload)
        mock.open()
        session = KWPSession(mock)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.02, keepalive_s=1.0)
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            mock.close()
        self.assertEqual(frame["rpm"], 710.0)            # OBD, não os 850 do perfil B17
        self.assertFalse(frame["verified"])              # perfil B17 presente: segue não verificado

    async def test_exclusive_pauses_device_io_and_publishes_paused_frames(self) -> None:
        class Counting(OneShotTimeoutDevice):
            def __init__(self) -> None:
                super().__init__()
                self.fail_session_once = False
                self.calls = 0

            def send_recv(self, data, timeout_ms=200):
                self.calls += 1
                return super().send_recv(data, timeout_ms)

        device = Counting()
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, asyncio.get_running_loop(),
                           interval_s=0.01, keepalive_s=1.0)
        poller.start()
        try:
            await asyncio.wait_for(queue.get(), timeout=2.0)       # ciclo normal
            with poller.exclusive():
                self.assertTrue(session.active)
                while not queue.empty():
                    queue.get_nowait()
                before = device.calls
                paused = await asyncio.wait_for(queue.get(), timeout=2.0)
                await asyncio.sleep(0.1)
                self.assertEqual(device.calls, before)             # nenhuma E/S no adaptador
            self.assertFalse(session.active)                       # sessão pode ter expirado: reabrir
            self.assertTrue(paused["paused"])
            self.assertIn("Scan", paused["message"])
            self.assertTrue(paused["conn"])
            while not queue.empty():
                queue.get_nowait()
            resumed = await asyncio.wait_for(queue.get(), timeout=2.0)
            self.assertFalse(resumed.get("paused", False))
            self.assertTrue(resumed["conn"])                        # reabriu a sessão sem erro
        finally:
            poller.stop()
            device.close()

    async def test_publishes_nrc_when_lid_is_refused(self) -> None:
        class RefusingDevice:
            data_source = "test_mock"

            def __init__(self) -> None:
                self.device = J2534DeviceMock()

            def open(self) -> None:
                self.device.open()

            def close(self) -> None:
                self.device.close()

            def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
                if data[:1] == b"\x21":
                    return bytes.fromhex("7f2112")
                return self.device.send_recv(data, timeout_ms)

        device = RefusingDevice()
        device.open()
        session = KWPSession(device)
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(
            session, queue, asyncio.get_running_loop(),
            interval_s=0.02, keepalive_s=1.0,
        )
        poller.start()
        try:
            frame = await asyncio.wait_for(queue.get(), timeout=2.0)
        finally:
            poller.stop()
            device.close()
        self.assertTrue(frame["conn"])
        self.assertFalse(frame["lid_available"])
        self.assertIsNone(frame["raw_lid01"])
        self.assertEqual(frame["lid_response"], "negative")
        self.assertEqual(frame["lid_nrc"], "12")
        self.assertEqual(frame["raw_lid_response"], "7f2112")


if __name__ == "__main__":
    unittest.main()
