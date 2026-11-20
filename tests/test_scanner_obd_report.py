"""Relatorio OBD do full_scan — conexao falsa, sem hardware."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd import scanner  # noqa: E402


class FakeConn:
    """Responde por payload de request; ausente = timeout."""

    def __init__(self, replies: dict[str, str]) -> None:
        self.replies = replies
        self.sent: list[bytes] = []

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def wait_frame(self, timeout: float = 1.0) -> bytes:
        reply = self.replies.get(self.sent[-1].hex())
        if reply is None:
            raise TimeoutError(f"sem resposta a {self.sent[-1].hex()}")
        return bytes.fromhex(reply)


class TestEngineObdReport(unittest.TestCase):
    def test_report_keeps_raw_hex_next_to_decoded_values(self) -> None:
        conn = FakeConn({
            "0100": "4100be1fa813",
            "0900": "490054000000",
            "03": "4300",
            "07": "47010133",
            "010c": "410c1af8",
            "010d": "410d32",
        })
        report = "\n".join(scanner._engine_obd_report(conn))

        self.assertIn("01 00: raw=4100be1fa813 -> 01 03 04 05 06 07 0C 0D", report)
        self.assertIn("09 00: raw=490054000000 -> 02 04 06", report)
        self.assertIn("DTCs confirmados: nenhum  raw=4300", report)
        self.assertIn("DTCs pendentes: ['P0133']  raw=47010133", report)
        self.assertIn("RPM: 1726.0 rpm  raw=410c1af8", report)
        self.assertIn("Velocidade: 50.0 km/h  raw=410d32", report)

    def test_timeouts_and_negative_responses_are_reported_not_raised(self) -> None:
        conn = FakeConn({"0902": "7f0912"})
        report = "\n".join(scanner._engine_obd_report(conn))

        self.assertIn("VIN: falhou", report)
        self.assertIn("raw=7f0912", report)
        self.assertIn("0100: TimeoutError", report)
        self.assertIn("PID 0x0C: falhou", report)
        self.assertIn("raw=sem resposta", report)


if __name__ == "__main__":
    unittest.main()
