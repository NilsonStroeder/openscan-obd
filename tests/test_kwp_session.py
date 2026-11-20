"""Sessão KWP 0xC0 — testes com mock, sem hardware."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.j2534_mock import J2534DeviceMock  # noqa: E402
from openscan_obd.gateway.kwp_session import KWPSession, KWPSessionError  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ecm_lid01_raw.hex"


class RefusingDevice:
    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        if data[:1] == b"\x10":
            return b"\x7f\x10\x12"
        return b"\x7f\x3e\x11"


class TestKWPSession(unittest.TestCase):
    def test_start_accepts_c0(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        self.assertTrue(session.active)

    def test_keep_alive_sends_tester_present(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        session.keep_alive()
        self.assertTrue(session.active)

    def test_rejected_session_raises_nrc(self) -> None:
        session = KWPSession(RefusingDevice())
        with self.assertRaises(KWPSessionError) as ctx:
            session.start()
        self.assertEqual(ctx.exception.nrc_code, 0x12)
        self.assertFalse(session.active)


if __name__ == "__main__":
    unittest.main()
