"""Transporte ELM327 (comandos AT + ISO-TP) com a interface do J2534Device.

Projeto: docs/sdd_elm327_transport.md. Testado só offline, com adaptador
falso; nenhum ELM327 real foi usado ainda. Suporta apenas ISO 15765-4 CAN
11 bits 500 kbit/s (ATSP6).
"""
from __future__ import annotations

import re
import time
from typing import Callable

from openscan_obd.gateway.j2534 import (
    RESPONSE_MATCH,
    RESPONSE_PENDING,
    classify_response,
)

PROMPT = b">"
DEFAULT_BAUDRATE = 38400
READ_MARGIN_S = 0.5
RESET_WAIT_S = 1.5
MAX_PENDING_RETRIES = 5
ATST_MAX = 0xFF
ATST_UNIT_MS = 4

# Serviços só de leitura/sessão, para os quais reenviar após 7F xx 78 é aceitável.
PENDING_RETRY_SERVICES = frozenset({0x01, 0x03, 0x07, 0x09, 0x10, 0x18, 0x1A, 0x21, 0x22, 0x3E})

_ERROR_MARKERS = (
    "CAN ERROR", "BUS ERROR", "BUS INIT", "UNABLE TO CONNECT", "BUFFER FULL",
    "STOPPED", "<DATA ERROR", "<RX ERROR", "FB ERROR", "LV RESET", "ACT ALERT",
    "ERR",
)
_HEX_LINE = re.compile(r"^[0-9A-F ]+$")


class ELM327Error(Exception):
    """Erro relatado pelo adaptador ou resposta que não pôde ser montada."""


class ELM327NoData(ELM327Error, TimeoutError):
    """`NO DATA` ou prazo de leitura esgotado — tratado como timeout."""


class ELM327Unsupported(ELM327Error):
    """O adaptador recusou (`?`) um comando AT obrigatório."""

    def __init__(self, command: str, reply: str) -> None:
        self.command = command
        self.reply = reply
        super().__init__(
            f"adaptador recusou {command!r} (resposta {reply!r}); "
            "clones ELM327 baratos costumam não ter esse comando"
        )


def _default_opener(port: str, baudrate: int):
    import serial

    return serial.serial_for_url(port, baudrate=baudrate, timeout=0.05)


def parse_frames(lines: list[str]) -> list[tuple[int, bytes]]:
    """Converte linhas `<header> <bytes>` (com ou sem espaços) em frames CAN."""
    frames: list[tuple[int, bytes]] = []
    for line in lines:
        text = line.strip().upper()
        if not _HEX_LINE.match(text):
            raise ELM327Error(f"linha inesperada do adaptador: {line!r}")
        if " " in text:
            parts = text.split()
            header, data = parts[0], "".join(parts[1:])
        else:
            header, data = text[:3], text[3:]
        if len(header) != 3 or len(data) % 2:
            raise ELM327Error(f"frame malformado: {line!r}")
        frames.append((int(header, 16), bytes.fromhex(data)))
    return frames


def reassemble_isotp(frames: list[bytes]) -> list[bytes]:
    """Remonta mensagens ISO-TP a partir dos dados de cada frame (com PCI)."""
    messages: list[bytes] = []
    buf = bytearray()
    expected = 0
    next_seq = 0
    for data in frames:
        if not data:
            raise ELM327Error("frame vazio")
        kind = data[0] >> 4
        if kind == 0x0:
            if expected:
                raise ELM327Error("single frame no meio de uma resposta multi-frame")
            size = data[0] & 0x0F
            if size == 0 or len(data) < 1 + size:
                raise ELM327Error(f"single frame com tamanho inválido: {data.hex()}")
            messages.append(bytes(data[1:1 + size]))
        elif kind == 0x1:
            if expected:
                raise ELM327Error("first frame antes do fim da resposta anterior")
            if len(data) < 2:
                raise ELM327Error(f"first frame curto: {data.hex()}")
            expected = ((data[0] & 0x0F) << 8) | data[1]
            buf = bytearray(data[2:])
            next_seq = 1
        elif kind == 0x2:
            if not expected:
                raise ELM327Error("consecutive frame sem first frame")
            seq = data[0] & 0x0F
            if seq != next_seq:
                raise ELM327Error(f"consecutive frame fora de ordem: esperado {next_seq:X}, veio {seq:X}")
            buf.extend(data[1:])
            next_seq = (next_seq + 1) & 0x0F
        else:
            raise ELM327Error(f"PCI não suportado: {data.hex()}")
        if expected and len(buf) >= expected:
            messages.append(bytes(buf[:expected]))
            buf = bytearray()
            expected = 0
    if expected:
        raise ELM327Error(f"resposta multi-frame incompleta: {len(buf)} de {expected} bytes")
    return messages


class ELM327Device:
    """Device ELM327 compatível com KWPSession, read_lid e KWPPoller."""

    data_source = "elm327"

    def __init__(
        self,
        port: str,
        txid: int = 0x7E0,
        rxid: int = 0x7E8,
        baudrate: int = DEFAULT_BAUDRATE,
        opener: Callable[[str, int], object] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.port = port
        self.txid = txid
        self.rxid = rxid
        self.baudrate = baudrate
        self._opener = opener or _default_opener
        self._sleep = sleep
        self._ser = None
        self._atst: int | None = None
        self.adapter_id: str | None = None
        self.at_log: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ ciclo
    def open(self) -> None:
        self._ser = self._opener(self.port, self.baudrate)
        self._atst = None
        self.at_log = []
        reset = self._command("ATZ", timeout_s=RESET_WAIT_S + 1.0, settle_s=RESET_WAIT_S)
        self.at_log.append(("ATZ", reset))
        for cmd in self.init_commands():
            reply = self._command(cmd)
            self.at_log.append((cmd, reply))
            if "?" in reply:
                raise ELM327Unsupported(cmd, reply)
        self.adapter_id = self._command("ATI") or None
        self.at_log.append(("ATI", self.adapter_id or ""))

    def init_commands(self) -> list[str]:
        tx = f"{self.txid:03X}"
        return [
            "ATE0", "ATL0", "ATS1", "ATH1", "ATCAF1", "ATSP6",
            f"ATSH{tx}", f"ATCRA{self.rxid:03X}",
            f"ATFCSH{tx}", "ATFCSD300000", "ATFCSM1",
            "ATAT1",
        ]

    def close(self) -> None:
        ser, self._ser = self._ser, None
        if ser is not None:
            try:
                ser.close()
            except Exception:  # noqa: BLE001
                pass

    def __enter__(self) -> "ELM327Device":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ---------------------------------------------------------------- pedidos
    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        if self._ser is None:
            raise ELM327Error("adaptador ELM327 não está aberto")
        if not data:
            raise ELM327Error("pedido vazio")
        sid = data[0]
        attempts = 0
        atst = self._atst_for(timeout_ms)
        while True:
            self._set_atst(atst)
            lines = self._request_lines(data.hex().upper(), timeout_ms / 1000)
            messages = self._messages(lines)
            pending = False
            for msg in messages:
                kind = classify_response(msg, sid, data)
                if kind == RESPONSE_MATCH:
                    return msg
                if kind == RESPONSE_PENDING:
                    pending = True
            if not pending:
                raise ELM327Error(
                    f"nenhuma resposta ao serviço 0x{sid:02X}: "
                    + (" | ".join(m.hex() for m in messages) or "vazio")
                )
            if sid not in PENDING_RETRY_SERVICES:
                raise ELM327Error(
                    f"serviço 0x{sid:02X} respondeu 7F 78 (pending) e não é reenviado"
                )
            attempts += 1
            if attempts > MAX_PENDING_RETRIES:
                raise ELM327NoData(f"serviço 0x{sid:02X}: {attempts} respostas 7F 78 seguidas")
            atst = ATST_MAX

    # ---------------------------------------------------------------- interno
    def _atst_for(self, timeout_ms: int) -> int:
        return max(1, min(ATST_MAX, -(-timeout_ms // ATST_UNIT_MS)))

    def _set_atst(self, value: int) -> None:
        if value == self._atst:
            return
        cmd = f"ATST{value:02X}"
        reply = self._command(cmd)
        if "?" in reply:
            raise ELM327Unsupported(cmd, reply)
        self._atst = value

    def _messages(self, lines: list[str]) -> list[bytes]:
        frames = [data for header, data in parse_frames(lines) if header == self.rxid]
        return reassemble_isotp(frames)

    def _request_lines(self, hex_payload: str, timeout_s: float) -> list[str]:
        raw = self._exchange(hex_payload, timeout_s + READ_MARGIN_S)
        lines = []
        for line in raw.replace("\n", "\r").split("\r"):
            text = line.strip()
            if not text or text.replace(" ", "") == hex_payload or text.startswith("SEARCHING"):
                continue
            upper = text.upper()
            if upper == "NO DATA":
                raise ELM327NoData(f"NO DATA para {hex_payload}")
            if upper == "?":
                raise ELM327Error(f"adaptador não entendeu {hex_payload!r}")
            if any(upper.startswith(m) for m in _ERROR_MARKERS):
                raise ELM327Error(f"adaptador: {text}")
            lines.append(text)
        if not lines:
            raise ELM327NoData(f"sem resposta para {hex_payload}")
        return lines

    def _command(self, cmd: str, timeout_s: float = 1.0, settle_s: float = 0.0) -> str:
        raw = self._exchange(cmd, timeout_s, settle_s=settle_s)
        lines = [
            ln.strip() for ln in raw.replace("\n", "\r").split("\r")
            if ln.strip() and ln.strip().replace(" ", "").upper() != cmd.upper()
        ]
        return " ".join(lines)

    def _exchange(self, text: str, timeout_s: float, settle_s: float = 0.0) -> str:
        ser = self._ser
        ser.write((text + "\r").encode("ascii"))
        if settle_s:
            self._sleep(settle_s)
        deadline = time.monotonic() + timeout_s
        buf = bytearray()
        while PROMPT not in buf:
            chunk = ser.read(64)
            if chunk:
                buf.extend(chunk)
            elif time.monotonic() >= deadline:
                raise ELM327NoData(f"sem prompt '>' após {text!r}: {bytes(buf)!r}")
            if PROMPT not in buf and time.monotonic() >= deadline + timeout_s:
                raise ELM327Error(f"adaptador não parou de enviar após {text!r}")
        return bytes(buf[: buf.index(PROMPT)]).decode("ascii", "replace")
