"""
Testa SerialElmSniffer.connect()/read_lines() contra um ELM327 SIMULADO
(FakeSerial), sem precisar de hardware nem estar no carro.

Objetivo: pegar bugs de LÓGICA de execução (não só sintaxe) antes da
próxima ida ao carro — já perdemos tempo real com dois bugs desse tipo
(ATSP0 e ATS0) que `py_compile` não detecta.

Roda com: python3 -m unittest tests/test_capture_fake_serial.py -v
(ou só "python3 tests/test_capture_fake_serial.py")
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.capture import SerialElmSniffer  # noqa: E402


class FakeSerial:
    """Simula um adaptador ELM327/STN respondendo via serial."""

    def __init__(self, replies: dict[str, str], stream_lines: list[str]):
        self.replies = replies  # comando (sem \r) -> texto de resposta (sem \r\r>)
        self.stream_lines = list(stream_lines)
        self.sent_commands: list[str] = []
        self._pending = b""
        self._streaming = False

    def write(self, data: bytes) -> int:
        text = data.decode().strip()
        self.sent_commands.append(text)
        if text == "ATMA":
            self._streaming = True
        else:
            reply = self.replies.get(text, "OK")
            self._pending += (reply + "\r\r>").encode()
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if self._pending:
            chunk, self._pending = self._pending[:n], self._pending[n:]
            return chunk
        if self._streaming and self.stream_lines:
            line = self.stream_lines.pop(0)
            data = (line + "\r").encode()
            chunk, rest = data[:n], data[n:]
            self._pending = rest
            return chunk
        return b""

    def close(self) -> None:
        pass


def _make_sniffer(replies: dict[str, str], stream_lines: list[str]) -> tuple[SerialElmSniffer, FakeSerial]:
    sniffer = SerialElmSniffer(port="FAKE")
    fake = FakeSerial(replies, stream_lines)
    return sniffer, fake


ALL_OK_REPLIES = {
    "ATZ": "ELM327 v1.3a",
    "ATE0": "OK",
    "ATL0": "OK",
    "ATS1": "OK",
    "ATH1": "OK",
    "ATD1": "OK",
    "ATSP6": "OK",
}


class TestConnectHappyPath(unittest.TestCase):
    """Cenário: adaptador suporta tudo, inclusive ATD1."""

    def test_connect_does_not_raise_and_sends_expected_sequence(self) -> None:
        sniffer, fake = _make_sniffer(ALL_OK_REPLIES, stream_lines=[])
        with mock.patch("openscan_obd.capture.serial.Serial", return_value=fake), \
             mock.patch("openscan_obd.capture.time.sleep"):
            sniffer.connect()

        # ATSP0 NUNCA deve ser usado (bug original) — e ATSP6 sim.
        self.assertNotIn("ATSP0", fake.sent_commands)
        self.assertIn("ATSP6", fake.sent_commands)
        # ATS0 (espacos off) NUNCA deve ser usado (bug original) — ATS1 sim.
        self.assertNotIn("ATS0", fake.sent_commands)
        self.assertIn("ATS1", fake.sent_commands)
        # ATMA deve ser o último comando enviado no preâmbulo.
        self.assertEqual(fake.sent_commands[-1], "ATMA")


class TestConnectOptionalATD1NotSupported(unittest.TestCase):
    """Cenário: firmware antigo responde '?' pro ATD1 — não deve abortar."""

    def test_atd1_failure_is_tolerated(self) -> None:
        replies = dict(ALL_OK_REPLIES)
        replies["ATD1"] = "?"
        sniffer, fake = _make_sniffer(replies, stream_lines=[])
        with mock.patch("openscan_obd.capture.serial.Serial", return_value=fake), \
             mock.patch("openscan_obd.capture.time.sleep"):
            # Não deve levantar excecao mesmo com ATD1 falhando.
            sniffer.connect()
        self.assertIn("ATD1", fake.sent_commands)
        self.assertIn("ATMA", fake.sent_commands)  # seguiu adiante


class TestConnectRequiredCommandFails(unittest.TestCase):
    """Cenário: um comando OBRIGATÓRIO (ATSP6) falha — deve abortar com erro claro."""

    def test_required_command_failure_raises(self) -> None:
        replies = dict(ALL_OK_REPLIES)
        replies["ATSP6"] = "?"
        sniffer, fake = _make_sniffer(replies, stream_lines=[])
        with mock.patch("openscan_obd.capture.serial.Serial", return_value=fake), \
             mock.patch("openscan_obd.capture.time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                sniffer.connect()
        self.assertIn("ATSP6", str(ctx.exception))


class TestReadLinesStreamsFrames(unittest.TestCase):
    """Confirma que read_lines() entrega as linhas de frame corretamente,
    incluindo o formato com DLC (ATD1) real documentado pelo driver can327."""

    def test_reads_expected_frame_lines(self) -> None:
        stream = [
            "7E8 8 0310410C1A000000",
            "7E9 6 0661010045220000",
            "BUFFER FULL",
        ]
        sniffer, fake = _make_sniffer(ALL_OK_REPLIES, stream_lines=stream)
        with mock.patch("openscan_obd.capture.serial.Serial", return_value=fake), \
             mock.patch("openscan_obd.capture.time.sleep"):
            sniffer.connect()

        gen = sniffer.read_lines()
        collected = [next(gen) for _ in range(len(stream))]
        self.assertEqual(collected, stream)


if __name__ == "__main__":
    unittest.main()
