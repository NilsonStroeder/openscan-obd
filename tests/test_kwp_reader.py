"""Leitor de LIDs KWP — mock offline, sem decodificar."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.j2534_mock import J2534DeviceMock  # noqa: E402
from openscan_obd.gateway.kwp_reader import (  # noqa: E402
    classify_lid_response,
    read_lid,
    read_lid_detailed,
    rx_id,
)
from openscan_obd.gateway.kwp_session import KWPSession  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ecm_lid01_raw.hex"


class TestRxId(unittest.TestCase):
    def test_ecm_rx(self) -> None:
        self.assertEqual(rx_id(0x7E0), 0x7E8)


class TestReadLid(unittest.TestCase):
    def test_transport_timeout_is_not_silently_converted_to_missing_lid(self) -> None:
        class TimeoutDevice:
            def send_recv(self, _data: bytes, timeout_ms: int = 200) -> bytes:
                raise TimeoutError("J2534 timeout")

        class TestSession:
            device = TimeoutDevice()

        with self.assertRaisesRegex(TimeoutError, "J2534 timeout"):
            read_lid(TestSession(), 0x7E0, 0x01)

    def test_recorded_b16_lid01_is_returned_without_a_builtin_minimum(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        self.assertEqual(read_lid(session, 0x7E0, 0x01), bytes.fromhex("001b0000"))

    def test_caller_supplied_minimum_rejects_short_payload(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        self.assertIsNone(read_lid(session, 0x7E0, 0x01, min_len=13))

    def test_unknown_lid_returns_none(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        self.assertIsNone(read_lid(session, 0x7E0, 0x21))

    def test_long_enough_payload_is_returned(self) -> None:
        payload = bytes(range(13))
        mock = J2534DeviceMock(lid01_payload=payload)
        mock.open()
        session = KWPSession(mock)
        session.start()
        self.assertEqual(read_lid(session, 0x7E0, 0x01, min_len=13), payload)


class TestReadLidDetailed(unittest.TestCase):
    def test_negative_response_keeps_nrc_and_raw_bytes(self) -> None:
        mock = J2534DeviceMock(FIXTURE)
        mock.open()
        session = KWPSession(mock)
        session.start()
        result = read_lid_detailed(session, 0x21)
        self.assertEqual(result.status, "negative")
        self.assertEqual(result.nrc, 0x31)
        self.assertEqual(result.raw, bytes.fromhex("7f2131"))
        self.assertIsNone(result.payload)

    def test_positive_response_strips_only_the_matching_echo(self) -> None:
        result = classify_lid_response(bytes.fromhex("6101001b0000"), 0x01)
        self.assertEqual(result.status, "positive")
        self.assertEqual(result.payload, bytes.fromhex("001b0000"))

    def test_echo_of_another_lid_is_unexpected(self) -> None:
        result = classify_lid_response(bytes.fromhex("6183aabb"), 0x01)
        self.assertEqual(result.status, "unexpected")
        self.assertIsNone(result.payload)
        self.assertEqual(result.raw, bytes.fromhex("6183aabb"))

    def test_other_service_and_empty_responses_are_unexpected(self) -> None:
        self.assertEqual(classify_lid_response(bytes.fromhex("50c0"), 0x01).status, "unexpected")
        self.assertEqual(classify_lid_response(b"", 0x01).status, "unexpected")
        self.assertEqual(classify_lid_response(None, 0x01).status, "unexpected")

    def test_negative_for_another_service_is_unexpected(self) -> None:
        result = classify_lid_response(bytes.fromhex("7f1012"), 0x01)
        self.assertEqual(result.status, "unexpected")
        self.assertIsNone(result.nrc)


if __name__ == "__main__":
    unittest.main()
