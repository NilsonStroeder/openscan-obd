"""Guarda de somente leitura: nada além de leitura chega ao adaptador (SDD 5.4, RF7)."""
from __future__ import annotations

import unittest

from openscan_obd.gateway.j2534_mock import J2534DeviceMock
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice, ReadOnlyViolation


class Spy:
    data_source = "spy"

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.ids = None

    def open(self) -> None: ...
    def close(self) -> None: ...

    def set_ids(self, tx: int, rx: int) -> None:
        self.ids = (tx, rx)

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        self.sent.append(bytes(data))
        return bytes([data[0] + 0x40])


ALLOWED = [
    "0100", "010c", "0200", "03", "06", "0600", "0601", "07", "0902", "090a", "0a",     # OBD
    "10c0", "3e", "3e00", "2101", "1a80", "1a82", "13ff00", "17ff00", "18ff00",  # KWP
]
FORBIDDEN = [
    "04", "11", "1101", "14ffffff", "2701", "2e0102", "3101", "31ff00", "3400",
    "3600", "3b80", "2f", "3d", "85", "28", "10c1", "1002", "a3",
]


class TestReadOnlyDevice(unittest.TestCase):
    def test_allowed_requests_reach_the_adapter_unchanged(self) -> None:
        spy = Spy()
        dev = ReadOnlyDevice(spy)
        for h in ALLOWED:
            with self.subTest(req=h):
                dev.send_recv(bytes.fromhex(h))
        self.assertEqual([r.hex() for r in spy.sent], ALLOWED)

    def test_forbidden_requests_raise_before_reaching_the_adapter(self) -> None:
        spy = Spy()
        dev = ReadOnlyDevice(spy)
        for h in FORBIDDEN:
            with self.subTest(req=h):
                with self.assertRaises(ReadOnlyViolation):
                    dev.send_recv(bytes.fromhex(h))
        self.assertEqual(spy.sent, [])

    def test_empty_request_is_refused(self) -> None:
        with self.assertRaises(ReadOnlyViolation):
            ReadOnlyDevice(Spy()).send_recv(b"")

    def test_only_session_c0_is_allowed_for_service_10(self) -> None:
        dev = ReadOnlyDevice(Spy())
        dev.send_recv(b"\x10\xc0")
        for sub in (0x01, 0x02, 0x81, 0x85, 0xC1):
            with self.subTest(sub=sub):
                with self.assertRaises(ReadOnlyViolation):
                    dev.send_recv(bytes([0x10, sub]))
        with self.assertRaises(ReadOnlyViolation):
            dev.send_recv(b"\x10")                      # sem subfunção

    def test_passthrough_of_the_rest_of_the_device_surface(self) -> None:
        spy = Spy()
        dev = ReadOnlyDevice(spy)
        dev.set_ids(0x7E1, 0x7E9)
        self.assertEqual(spy.ids, (0x7E1, 0x7E9))
        self.assertEqual(dev.data_source, "spy")

    def test_wraps_the_real_mock_without_changing_reads(self) -> None:
        mock = J2534DeviceMock()
        mock.open()
        dev = ReadOnlyDevice(mock)
        self.assertEqual(dev.send_recv(b"\x01\x0c"), bytes.fromhex("410c0b18"))

    def test_probe_dtc_allow_list_is_the_only_way_to_send_a3(self) -> None:
        spy = Spy()
        dev = ReadOnlyDevice(spy, extra_allowed={0xA3})
        dev.send_recv(b"\xa3")
        self.assertEqual(spy.sent, [b"\xa3"])
        with self.assertRaises(ReadOnlyViolation):
            ReadOnlyDevice(Spy()).send_recv(b"\xa3")
        # extra_allowed não abre os SIDs de escrita
        with self.assertRaises(ReadOnlyViolation):
            dev.send_recv(b"\x04")

    def test_extra_allowed_cannot_include_write_services(self) -> None:
        for sid in (0x04, 0x14, 0x27, 0x2E, 0x31, 0x10):
            with self.subTest(sid=sid):
                with self.assertRaises(ValueError):
                    ReadOnlyDevice(Spy(), extra_allowed={sid})


if __name__ == "__main__":
    unittest.main()
