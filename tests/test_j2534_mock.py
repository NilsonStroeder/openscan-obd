"""Testa J2534DeviceMock offline — sem DLL nem veículo."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.j2534_mock import (  # noqa: E402
    J2534DeviceMock,
    load_hex_fixture,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ecm_lid01_raw.hex"


class TestHexFixture(unittest.TestCase):
    def test_recorded_ecm_lid01_bytes(self) -> None:
        # Fonte: logs/ecm_lid_sweep_20261024_164933.json, ECM 0x7E0 sessão 0xC0.
        self.assertEqual(load_hex_fixture(FIXTURE), bytes.fromhex("01001b0000"))


class TestJ2534DeviceMock(unittest.TestCase):
    def test_send_recv_requires_open(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        with self.assertRaises(RuntimeError):
            mock.send_recv(b"\x10\xc0")

    def test_start_session_positive(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        try:
            self.assertEqual(mock.send_recv(b"\x10\xc0"), b"\x50\xc0")
        finally:
            mock.close()

    def test_tester_present(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        try:
            self.assertEqual(mock.send_recv(b"\x3e\x00"), b"\x7e\x00")
        finally:
            mock.close()

    def test_read_lid01_wraps_recorded_payload(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        try:
            resp = mock.send_recv(b"\x21\x01")
        finally:
            mock.close()
        self.assertEqual(resp, bytes.fromhex("6101001b0000"))

    def test_unknown_lid_is_out_of_range(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        try:
            self.assertEqual(mock.send_recv(b"\x21\x21"), b"\x7f\x21\x31")
        finally:
            mock.close()

    def test_injected_payload_without_lid_echo(self) -> None:
        mock = J2534DeviceMock(lid01_payload=b"\x00" * 13)
        mock.open()
        try:
            self.assertEqual(mock.send_recv(b"\x21\x01"), b"\x61\x01" + b"\x00" * 13)
        finally:
            mock.close()


if __name__ == "__main__":
    unittest.main()
