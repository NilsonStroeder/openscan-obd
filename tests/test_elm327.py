"""Transporte ELM327 com adaptador falso — sem serial real, sem veículo."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.elm327 import (  # noqa: E402
    ELM327Device,
    ELM327Error,
    ELM327NoData,
    ELM327Unsupported,
    parse_frames,
    reassemble_isotp,
)
from openscan_obd.gateway.kwp_reader import read_lid_detailed  # noqa: E402
from openscan_obd.gateway.kwp_session import KWPSession  # noqa: E402

FIELD = Path(__file__).resolve().parent / "fixtures" / "lid01_field_20261023.json"


def isotp_lines(rx: int, payload: bytes, spaces: bool = True, pad: int = 0xAA) -> list[str]:
    """Frames como o ELM327 imprime com ATH1 ATCAF1 (header + PCI + dados)."""
    frames: list[bytes] = []
    if len(payload) <= 7:
        frames.append(bytes([len(payload)]) + payload)
    else:
        size = len(payload)
        frames.append(bytes([0x10 | (size >> 8), size & 0xFF]) + payload[:6])
        rest, seq = payload[6:], 1
        while rest:
            frames.append(bytes([0x20 | seq]) + rest[:7])
            rest, seq = rest[7:], (seq + 1) & 0x0F
    lines = []
    for frame in frames:
        frame = frame + bytes([pad]) * (8 - len(frame))
        sep = " " if spaces else ""
        lines.append(f"{rx:03X}{sep}" + sep.join(f"{b:02X}" for b in frame))
    return lines


class FakeElm:
    """Adaptador ELM327 falso: responde a AT e a pedidos configurados."""

    def __init__(self, responses=None, refuse=(), version="ELM327 v1.5", echo=False):
        self.responses = dict(responses or {})
        self.refuse = {c.upper() for c in refuse}
        self.version = version
        self.echo = echo
        self.commands: list[str] = []
        self.calls: dict[str, int] = {}
        self._out = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        cmd = data.decode("ascii").strip().upper()
        self.commands.append(cmd)
        self.calls[cmd] = self.calls.get(cmd, 0) + 1
        if cmd.startswith("AT"):
            if cmd in self.refuse or any(cmd.startswith(r) for r in self.refuse):
                reply = ["?"]
            elif cmd == "ATZ":
                reply = ["", self.version]
            elif cmd == "ATI":
                reply = [self.version]
            else:
                reply = ["OK"]
        else:
            reply = self.responses.get(cmd, ["NO DATA"])
            if callable(reply):
                reply = reply(self.calls[cmd])
        text = (cmd + "\r" if self.echo else "") + "\r".join(reply) + "\r\r>"
        self._out.extend(text.encode("ascii"))

    def read(self, size: int) -> bytes:
        chunk = bytes(self._out[:size])
        del self._out[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


def make_device(fake: FakeElm, txid=0x7E0, rxid=0x7E8) -> ELM327Device:
    dev = ELM327Device("FAKE", txid=txid, rxid=rxid,
                       opener=lambda _p, _b: fake, sleep=lambda _s: None)
    dev.open()
    return dev


class TestInit(unittest.TestCase):
    def test_init_sequence_and_adapter_id(self) -> None:
        fake = FakeElm()
        dev = make_device(fake, txid=0x745, rxid=0x765)
        self.assertEqual(dev.adapter_id, "ELM327 v1.5")
        self.assertEqual(fake.commands[0], "ATZ")
        for cmd in ("ATE0", "ATH1", "ATCAF1", "ATSP6", "ATSH745", "ATCRA765",
                    "ATFCSH745", "ATFCSD300000", "ATFCSM1"):
            self.assertIn(cmd, fake.commands)
        dev.close()
        self.assertTrue(fake.closed)

    def test_clone_without_flow_control_is_rejected(self) -> None:
        fake = FakeElm(refuse=("ATFCSH",), version="ELM327 v2.1")
        dev = ELM327Device("FAKE", opener=lambda _p, _b: fake, sleep=lambda _s: None)
        with self.assertRaises(ELM327Unsupported) as ctx:
            dev.open()
        self.assertTrue(ctx.exception.command.startswith("ATFCSH"))
        self.assertIn(("ATFCSH7E0", "?"), dev.at_log)

    def test_send_requires_open(self) -> None:
        with self.assertRaises(ELM327Error):
            ELM327Device("FAKE").send_recv(bytes.fromhex("0100"))


class TestParsing(unittest.TestCase):
    def test_single_frame_with_padding_and_without_spaces(self) -> None:
        frames = parse_frames(["7E8 06 41 00 BE 1F A8 13 AA", "7E806410DBE1FA813"])
        self.assertEqual(frames[0], (0x7E8, bytes.fromhex("064100be1fa813aa")))
        self.assertEqual(reassemble_isotp([frames[0][1]]), [bytes.fromhex("4100be1fa813")])
        self.assertEqual(frames[1][0], 0x7E8)

    def test_multiframe_reassembly(self) -> None:
        payload = bytes(range(20))
        lines = isotp_lines(0x7E9, payload)
        frames = [d for _h, d in parse_frames(lines)]
        self.assertEqual(reassemble_isotp(frames), [payload])

    def test_out_of_order_consecutive_frame(self) -> None:
        frames = [bytes.fromhex("100a0102030405 06".replace(" ", "")),
                  bytes.fromhex("2207080910")]
        with self.assertRaises(ELM327Error):
            reassemble_isotp(frames)

    def test_incomplete_multiframe(self) -> None:
        with self.assertRaises(ELM327Error):
            reassemble_isotp([bytes.fromhex("1014010203040506")])

    def test_garbage_line(self) -> None:
        with self.assertRaises(ELM327Error):
            parse_frames(["hello"])


class TestSendRecv(unittest.TestCase):
    def test_kwp_session_and_short_ecm_lid(self) -> None:
        fake = FakeElm(responses={
            "10C0": isotp_lines(0x7E8, bytes.fromhex("50c0")),
            "2101": isotp_lines(0x7E8, bytes.fromhex("6101001b0000")),
            "2121": isotp_lines(0x7E8, bytes.fromhex("7f2112")),
        })
        dev = make_device(fake)
        session = KWPSession(dev)
        session.start()
        self.assertTrue(session.active)
        ok = read_lid_detailed(session, 0x01)
        self.assertEqual((ok.status, ok.payload), ("positive", bytes.fromhex("001b0000")))
        refused = read_lid_detailed(session, 0x21)
        self.assertEqual((refused.status, refused.nrc), ("negative", 0x12))

    def test_real_tcm_lid01_payload_over_multiframe(self) -> None:
        capture = json.loads(FIELD.read_text(encoding="utf-8"))["captures"][0]
        payload = bytes.fromhex(capture["hex"])          # 69 bytes, com eco do LID
        self.assertEqual(len(payload), 69)
        fake = FakeElm(responses={"2101": isotp_lines(0x7E9, b"\x61" + payload, spaces=False)})
        dev = make_device(fake, txid=0x7E1, rxid=0x7E9)
        self.assertEqual(dev.send_recv(bytes.fromhex("2101"), timeout_ms=500), b"\x61" + payload)

    def test_echo_searching_and_other_header_are_ignored(self) -> None:
        fake = FakeElm(echo=True, responses={
            "0100": ["SEARCHING...", "7E9 03 7F 01 11 AA AA AA AA"]
            + isotp_lines(0x7E8, bytes.fromhex("4100be1fa813")),
        })
        dev = make_device(fake)
        self.assertEqual(dev.send_recv(bytes.fromhex("0100")), bytes.fromhex("4100be1fa813"))

    def test_no_data_is_timeout(self) -> None:
        dev = make_device(FakeElm())
        with self.assertRaises(TimeoutError):
            dev.send_recv(bytes.fromhex("2101"))
        with self.assertRaises(ELM327NoData):
            dev.send_recv(bytes.fromhex("2101"))

    def test_bus_error_is_reported(self) -> None:
        dev = make_device(FakeElm(responses={"2101": ["CAN ERROR"]}))
        with self.assertRaisesRegex(ELM327Error, "CAN ERROR"):
            dev.send_recv(bytes.fromhex("2101"))

    def test_pending_followed_by_final_answer_in_same_window(self) -> None:
        fake = FakeElm(responses={
            "2101": isotp_lines(0x7E8, bytes.fromhex("7f2178"))
            + isotp_lines(0x7E8, bytes.fromhex("6101001b0000")),
        })
        dev = make_device(fake)
        self.assertEqual(dev.send_recv(bytes.fromhex("2101")), bytes.fromhex("6101001b0000"))
        self.assertEqual(fake.calls["2101"], 1)

    def test_pending_alone_resends_read_service_with_max_timeout(self) -> None:
        def reply(call: int) -> list[str]:
            if call == 1:
                return isotp_lines(0x7E8, bytes.fromhex("7f2178"))
            return isotp_lines(0x7E8, bytes.fromhex("6101001b0000"))

        fake = FakeElm(responses={"2101": reply})
        dev = make_device(fake)
        self.assertEqual(dev.send_recv(bytes.fromhex("2101")), bytes.fromhex("6101001b0000"))
        self.assertEqual(fake.calls["2101"], 2)
        self.assertIn("ATSTFF", fake.commands)

    def test_pending_on_unlisted_service_is_not_resent(self) -> None:
        fake = FakeElm(responses={"3101": isotp_lines(0x7E8, bytes.fromhex("7f3178"))})
        dev = make_device(fake)
        with self.assertRaisesRegex(ELM327Error, "não é reenviado"):
            dev.send_recv(bytes.fromhex("3101"))
        self.assertEqual(fake.calls["3101"], 1)

    def test_atst_only_sent_when_timeout_changes(self) -> None:
        fake = FakeElm(responses={"3E": isotp_lines(0x7E8, bytes.fromhex("7e"))})
        dev = make_device(fake)
        dev.send_recv(b"\x3e", timeout_ms=200)
        dev.send_recv(b"\x3e", timeout_ms=200)
        dev.send_recv(b"\x3e", timeout_ms=400)
        self.assertEqual([c for c in fake.commands if c.startswith("ATST")], ["ATST32", "ATST64"])



class TestIntegration(unittest.TestCase):
    def test_api_builds_elm_device_for_ecm(self) -> None:
        from openscan_obd.api.main import _make_device

        dev = _make_device(False, "ignored.dll", "COM5")
        self.assertIsInstance(dev, ELM327Device)
        self.assertEqual((dev.port, dev.txid, dev.rxid), ("COM5", 0x7E0, 0x7E8))

    def test_elm_check_reports_refused_command(self) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from openscan_obd.cli import main

        fake = FakeElm(refuse=("ATFCSD",), version="ELM327 v2.1")
        original = ELM327Device.__init__

        def init(self, port, **kwargs):
            original(self, port, opener=lambda _p, _b: fake, sleep=lambda _s: None, **kwargs)

        with patch.object(ELM327Device, "__init__", init):
            result = CliRunner().invoke(main, ["elm-check", "--port", "COM5"])
        self.assertIn("RECUSADO", result.output)
        self.assertIn("[??] ATFCSD300000", result.output)
        self.assertNotEqual(result.exit_code, 0)

    def test_elm_check_probe_ecm(self) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from openscan_obd.cli import main

        fake = FakeElm(responses={"0100": isotp_lines(0x7E8, bytes.fromhex("4100be1fa813"))})
        original = ELM327Device.__init__

        def init(self, port, **kwargs):
            original(self, port, opener=lambda _p, _b: fake, sleep=lambda _s: None, **kwargs)

        with patch.object(ELM327Device, "__init__", init):
            result = CliRunner().invoke(main, ["elm-check", "--port", "COM5", "--probe-ecm"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Adaptador: ELM327 v1.5", result.output)
        self.assertIn("01 00 -> 4100be1fa813", result.output)
        self.assertEqual(fake.commands[-1], "0100")

if __name__ == "__main__":
    unittest.main()
