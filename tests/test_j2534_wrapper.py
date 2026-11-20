"""Testa o wrapper J2534 com uma DLL falsa — sem hardware."""
from __future__ import annotations

import sys
import unittest
from ctypes import POINTER, c_ulong, cast
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.j2534 import (  # noqa: E402
    ERR_BUFFER_EMPTY,
    ERR_FAILED,
    ERR_TIMEOUT,
    STATUS_NOERROR,
    J2534Device,
    J2534Error,
    PassThruMsg,
    classify_response,
    error_name,
    pack_can_id,
    payload_from_msg,
)


class FakeLib:
    def __init__(self, reads: list[tuple[int, bytes, int]] | None = None) -> None:
        self.reads = list(reads or [])
        self.written: list[bytes] = []
        self.opened = False
        self.connected = False

    def PassThruOpen(self, _name, p_device):
        cast(p_device, POINTER(c_ulong)).contents.value = 1
        self.opened = True
        return STATUS_NOERROR

    def PassThruClose(self, _device):
        self.opened = False
        return STATUS_NOERROR

    def PassThruConnect(self, _device, _proto, _flags, _baud, p_channel):
        cast(p_channel, POINTER(c_ulong)).contents.value = 2
        self.connected = True
        return STATUS_NOERROR

    def PassThruDisconnect(self, _channel):
        self.connected = False
        return STATUS_NOERROR

    def PassThruStartMsgFilter(self, *_args):
        return STATUS_NOERROR

    def PassThruWriteMsgs(self, _channel, p_msg, _count, _timeout):
        msg = cast(p_msg, POINTER(PassThruMsg)).contents
        self.written.append(payload_from_msg(msg))
        return STATUS_NOERROR

    def PassThruReadMsgs(self, _channel, p_msg, p_count, _timeout):
        if not self.reads:
            return ERR_TIMEOUT
        code, payload, rxstatus = self.reads.pop(0)
        if code != STATUS_NOERROR:
            return code
        packed = pack_can_id(0x7E8) + payload
        msg = cast(p_msg, POINTER(PassThruMsg)).contents
        msg.DataSize = len(packed)
        msg.RxStatus = rxstatus
        for i, byte in enumerate(packed):
            msg.Data[i] = byte
        cast(p_count, POINTER(c_ulong)).contents.value = 1
        return STATUS_NOERROR

    def PassThruGetLastError(self, buf):
        return STATUS_NOERROR


def _loader_from(lib: FakeLib):
    def loader(_path: str) -> FakeLib:
        return lib
    return loader


class TestErrorMapping(unittest.TestCase):
    def test_named_codes(self) -> None:
        self.assertEqual(error_name(ERR_TIMEOUT), "ERR_TIMEOUT")
        self.assertEqual(error_name(ERR_BUFFER_EMPTY), "ERR_BUFFER_EMPTY")
        self.assertEqual(error_name(ERR_FAILED), "ERR_FAILED")

    def test_j2534_error_keeps_code(self) -> None:
        err = J2534Error(ERR_TIMEOUT, "ERR_TIMEOUT")
        self.assertEqual(err.code, ERR_TIMEOUT)


class TestResetChannel(unittest.TestCase):
    def test_reset_channel_reconnects_without_reopening_the_device(self) -> None:
        # GD101 2026-11-16: PassThruClose + PassThruOpen => ERR_DEVICE_NOT_CONNECTED.
        lib = FakeLib()
        calls: list[str] = []
        for name in ("PassThruOpen", "PassThruClose", "PassThruConnect", "PassThruDisconnect"):
            orig = getattr(lib, name)
            setattr(lib, name, lambda *a, _o=orig, _n=name: (calls.append(_n), _o(*a))[1])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        calls.clear()
        dev.set_ids(0x740, 0x760)
        dev.reset_channel()
        self.assertEqual(calls, ["PassThruDisconnect", "PassThruConnect"])
        self.assertEqual((dev.txid, dev.rxid), (0x740, 0x760))     # volta ao par atual
        resp_lib_ok = lib.connected
        self.assertTrue(resp_lib_ok)

    def test_reset_channel_requires_open(self) -> None:
        with self.assertRaises(J2534Error):
            J2534Device("fake.dll", loader=_loader_from(FakeLib())).reset_channel()


class TestSendRecv(unittest.TestCase):
    def test_send_recv_roundtrip(self) -> None:
        lib = FakeLib(reads=[(STATUS_NOERROR, b"\x50\xc0", 0)])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            resp = dev.send_recv(b"\x10\xc0", timeout_ms=100)
        finally:
            dev.close()
        self.assertEqual(resp, b"\x50\xc0")
        self.assertEqual(lib.written, [b"\x10\xc0"])

    def test_buffer_empty_then_data(self) -> None:
        lib = FakeLib(reads=[
            (ERR_BUFFER_EMPTY, b"", 0),
            (STATUS_NOERROR, b"\x7e\x00", 0),
        ])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            resp = dev.send_recv(b"\x3e\x00", timeout_ms=100)
        finally:
            dev.close()
        self.assertEqual(resp, b"\x7e\x00")

    def test_timeout_raises(self) -> None:
        lib = FakeLib(reads=[(ERR_TIMEOUT, b"", 0)])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            with self.assertRaises(J2534Error) as ctx:
                dev.send_recv(b"\x21\x01", timeout_ms=50)
            self.assertEqual(ctx.exception.code, ERR_TIMEOUT)
        finally:
            dev.close()

    def test_response_pending_is_skipped_until_final_answer(self) -> None:
        lib = FakeLib(reads=[
            (STATUS_NOERROR, bytes.fromhex("7f2178"), 0),
            (STATUS_NOERROR, bytes.fromhex("7f2178"), 0),
            (STATUS_NOERROR, bytes.fromhex("6101001b"), 0),
        ])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            resp = dev.send_recv(bytes.fromhex("2101"), timeout_ms=50)
        finally:
            dev.close()
        self.assertEqual(resp, bytes.fromhex("6101001b"))

    def test_stale_frame_of_other_service_is_discarded(self) -> None:
        lib = FakeLib(reads=[
            (STATUS_NOERROR, bytes.fromhex("50c0"), 0),    # resposta atrasada a 10 C0
            (STATUS_NOERROR, bytes.fromhex("7f2112"), 0),  # resposta final ao 21 05
        ])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            resp = dev.send_recv(bytes.fromhex("2105"), timeout_ms=50)
        finally:
            dev.close()
        self.assertEqual(resp, bytes.fromhex("7f2112"))

    def test_late_obd_reply_of_another_pid_is_not_taken_for_this_pid(self) -> None:
        # Bug real (2026-11-16): resposta atrasada do PID 0C (RPM) aceita como resposta do 0D
        # (velocidade), porque ambas são serviço 0x41. Mostrava velocidade = RPM no dashboard.
        lib = FakeLib(reads=[
            (STATUS_NOERROR, bytes.fromhex("410c12a8"), 0),   # atrasada: RPM
            (STATUS_NOERROR, bytes.fromhex("410d00"), 0),     # a resposta certa
        ])
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            resp = dev.send_recv(bytes.fromhex("010d"), timeout_ms=50)
        finally:
            dev.close()
        self.assertEqual(resp, bytes.fromhex("410d00"))

    def test_classify_response_checks_the_pid_for_obd_services(self) -> None:
        req = bytes.fromhex("010d")
        self.assertEqual(classify_response(bytes.fromhex("410d00"), 0x01, req), "match")
        self.assertEqual(classify_response(bytes.fromhex("410c12a8"), 0x01, req), "other")
        self.assertEqual(classify_response(bytes.fromhex("7f0112"), 0x01, req), "match")
        self.assertEqual(classify_response(bytes.fromhex("4900"), 0x09, bytes.fromhex("0902")), "other")
        self.assertEqual(classify_response(bytes.fromhex("4902"), 0x09, bytes.fromhex("0902")), "match")
        # sem pedido completo (ou serviço que não ecoa PID) o comportamento é o de sempre
        self.assertEqual(classify_response(bytes.fromhex("410c12a8"), 0x01), "match")
        self.assertEqual(classify_response(bytes.fromhex("6101"), 0x21, bytes.fromhex("2101")), "match")
        self.assertEqual(classify_response(bytes.fromhex("43"), 0x03, bytes.fromhex("03")), "match")

    def test_endless_pending_raises(self) -> None:
        lib = FakeLib(reads=[(STATUS_NOERROR, bytes.fromhex("7f2178"), 0)] * 20)
        dev = J2534Device("fake.dll", loader=_loader_from(lib))
        dev.open()
        try:
            with self.assertRaises(J2534Error) as ctx:
                dev.send_recv(bytes.fromhex("2101"), timeout_ms=50, pending_timeout_ms=50)
            self.assertEqual(ctx.exception.code, ERR_TIMEOUT)
            self.assertIn("0x78", str(ctx.exception))
        finally:
            dev.close()

    def test_failed_on_open(self) -> None:
        class Boom(FakeLib):
            def PassThruOpen(self, _name, _p_device):
                return ERR_FAILED

        dev = J2534Device("fake.dll", loader=_loader_from(Boom()))
        with self.assertRaises(J2534Error) as ctx:
            dev.open()
        self.assertEqual(ctx.exception.code, ERR_FAILED)

    def test_send_recv_requires_open(self) -> None:
        dev = J2534Device("fake.dll", loader=_loader_from(FakeLib()))
        with self.assertRaises(J2534Error):
            dev.send_recv(b"\x10\xc0")


class TestMsgHelpers(unittest.TestCase):
    def test_classify_response(self) -> None:
        self.assertEqual(classify_response(bytes.fromhex("6101"), 0x21), "match")
        self.assertEqual(classify_response(bytes.fromhex("7f2112"), 0x21), "match")
        self.assertEqual(classify_response(bytes.fromhex("7f2178"), 0x21), "pending")
        self.assertEqual(classify_response(bytes.fromhex("7f1078"), 0x21), "other")
        self.assertEqual(classify_response(bytes.fromhex("50c0"), 0x21), "other")
        self.assertEqual(classify_response(b"", 0x21), "other")

    def test_pack_can_id(self) -> None:
        self.assertEqual(pack_can_id(0x7E0), b"\x00\x00\x07\xe0")

    def test_payload_from_msg(self) -> None:
        msg = PassThruMsg()
        packed = pack_can_id(0x7E8) + b"\x61\x01"
        msg.DataSize = len(packed)
        for i, byte in enumerate(packed):
            msg.Data[i] = byte
        self.assertEqual(payload_from_msg(msg), b"\x61\x01")


if __name__ == "__main__":
    unittest.main()
