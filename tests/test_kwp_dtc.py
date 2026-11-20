from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from click.testing import CliRunner

from openscan_obd.cli import main
from openscan_obd.gateway.kwp_dtc import build_read_dtcs_request, read_dtcs_raw
from openscan_obd.gateway.kwp_session import KWPSession


class FakeDevice:
    data_source = "test_mock"

    def __init__(self, response: bytes = b"\x58\x02\x12\x34") -> None:
        self.response = response
        self.requests: list[bytes] = []
        self.opened = False

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.requests.append(data)
        if data[0] == 0x10:
            return bytes((0x50, data[1]))
        if data[0] == 0x18:
            return self.response
        raise AssertionError(f"unexpected service 0x{data[0]:02X}")


class TestKwpDtcRead(unittest.TestCase):
    def test_builds_read_only_request_with_explicit_status_mask(self) -> None:
        self.assertEqual(build_read_dtcs_request(0xFF), b"\x18\xff")
        with self.assertRaises(ValueError):
            build_read_dtcs_request(0x100)

    def test_builds_request_with_optional_group(self) -> None:
        self.assertEqual(build_read_dtcs_request(0x02, None), b"\x18\x02")
        self.assertEqual(build_read_dtcs_request(0x02, 0xFF00), b"\x18\x02\xff\x00")
        self.assertEqual(build_read_dtcs_request(0xFF, 0x0000), b"\x18\xff\x00\x00")
        self.assertEqual(build_read_dtcs_request(0x00, 0xFFFF), b"\x18\x00\xff\xff")

    def test_rejects_invalid_ranges(self) -> None:
        for mask, group in ((-1, None), (0x100, 0xFF00), (0x02, -1), (0x02, 0x10000)):
            with self.subTest(mask=mask, group=group), self.assertRaises(ValueError):
                build_read_dtcs_request(mask, group)

    def test_read_with_group_sends_four_bytes_and_keeps_raw(self) -> None:
        device = FakeDevice(b"\x58\x00")
        session = KWPSession(device)
        session.start()

        result = read_dtcs_raw(session, 0x02, group=0xFF00)

        self.assertEqual(device.requests[-1], b"\x18\x02\xff\x00")
        self.assertEqual(result.request, b"\x18\x02\xff\x00")
        self.assertEqual(result.group, 0xFF00)
        self.assertEqual(result.raw_response, b"\x58\x00")
        self.assertEqual(result.response_data, b"\x00")

    def test_preserves_positive_response_without_decoding_dtc_bytes(self) -> None:
        device = FakeDevice(b"\x58\x02\x12\x34")
        session = KWPSession(device)
        session.start()

        result = read_dtcs_raw(session, 0xFF)

        self.assertTrue(result.positive)
        self.assertEqual(result.raw_response, b"\x58\x02\x12\x34")
        self.assertEqual(result.response_data, b"\x02\x12\x34")
        self.assertEqual(device.requests, [b"\x10\xc0", b"\x18\xff"])

    def test_preserves_negative_response_nrc(self) -> None:
        device = FakeDevice(b"\x7f\x18\x31")
        session = KWPSession(device)
        session.start()

        result = read_dtcs_raw(session, 0x01)

        self.assertFalse(result.positive)
        self.assertEqual(result.nrc, 0x31)
        self.assertEqual(result.raw_response, b"\x7f\x18\x31")

    def test_refuses_read_when_session_is_inactive(self) -> None:
        session = KWPSession(FakeDevice())

        with self.assertRaisesRegex(RuntimeError, "sessão KWP inativa"):
            read_dtcs_raw(session, 0xFF)

    def test_cli_uses_separate_device_and_outputs_raw_only_response(self) -> None:
        device = FakeDevice()
        with patch(
            "openscan_obd.gateway.j2534.J2534Device",
            return_value=device,
        ):
            result = CliRunner().invoke(main, [
                "read-kwp-dtcs",
                "--dll", "test.dll",
                "--txid", "7E0",
                "--rxid", "7E8",
                "--session", "C0",
                "--status-mask", "FF",
                "--json",
            ])

        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertTrue(report["read_only"])
        self.assertEqual(report["raw_response"], "58021234")
        self.assertIsNone(report["decoded_dtcs"])
        self.assertEqual(device.requests, [b"\x10\xc0", b"\x18\xff"])
        self.assertFalse(device.opened)
        self.assertEqual(report["request"], "18 FF")
        self.assertEqual(report["request_format"], "status_only")
        self.assertIsNone(report["group"])

    def _invoke_with_group(self, group: str, *extra: str):
        device = FakeDevice()
        with patch(
            "openscan_obd.gateway.j2534.J2534Device",
            return_value=device,
        ):
            result = CliRunner().invoke(main, [
                "read-kwp-dtcs",
                "--dll", "test.dll",
                "--txid", "7E1",
                "--rxid", "7E9",
                "--session", "C0",
                "--status-mask", "FF",
                "--group", group,
                *extra,
            ])
        return result, device

    def test_cli_group_is_sent_and_reported_in_json(self) -> None:
        result, device = self._invoke_with_group("FF00", "--json")

        self.assertEqual(result.exit_code, 0, result.output)
        report = json.loads(result.output)
        self.assertEqual(device.requests, [b"\x10\xc0", b"\x18\xff\xff\x00"])
        self.assertEqual(report["request"], "18 FF FF 00")
        self.assertEqual(report["request_format"], "status_and_group")
        self.assertEqual(report["group"], "0xFF00")
        self.assertEqual(report["raw_response"], "58021234")

    def test_cli_group_is_shown_in_text_output(self) -> None:
        result, _device = self._invoke_with_group("ff00")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Pedido KWP 0x18: 18 FF FF 00", result.output)

    def test_cli_rejects_group_that_is_not_four_hex_digits(self) -> None:
        for bad in ("FF", "FF000", "GG00"):
            with self.subTest(group=bad):
                result, device = self._invoke_with_group(bad)
                self.assertEqual(result.exit_code, 2, result.output)
                self.assertEqual(device.requests, [])

    def test_cli_rejects_invalid_can_id_before_opening_device(self) -> None:
        result = CliRunner().invoke(main, [
            "read-kwp-dtcs",
            "--dll", "test.dll",
            "--txid", "800",
            "--rxid", "7E8",
            "--session", "C0",
            "--status-mask", "FF",
        ])

        self.assertEqual(result.exit_code, 2)
        self.assertIn("IDs CAN de 11 bits", result.output)


if __name__ == "__main__":
    unittest.main()
