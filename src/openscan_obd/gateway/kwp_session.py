"""Gerenciador de sessão KWP Nissan 0xC0.

Abre a sessão (10 C0 → 50 C0) e envia TesterPresent (0x3E) no keep-alive.
Não faz polling de LIDs.
"""
from __future__ import annotations

SERVICE_START_SESSION = 0x10
SERVICE_TESTER_PRESENT = 0x3E
POSITIVE_START = 0x50
NEGATIVE = 0x7F
DEFAULT_SESSION = 0xC0


class KWPSessionError(Exception):
    def __init__(self, nrc_code: int, message: str = "") -> None:
        self.nrc_code = nrc_code
        super().__init__(message or f"KWP NRC 0x{nrc_code:02X}")


class KWPSession:
    def __init__(self, device, session_type: int = DEFAULT_SESSION, timeout_ms: int = 500) -> None:
        self.device = device
        self.session_type = session_type
        self.timeout_ms = timeout_ms
        self.active = False

    def start(self) -> None:
        resp = self.device.send_recv(
            bytes([SERVICE_START_SESSION, self.session_type]),
            timeout_ms=self.timeout_ms,
        )
        if not resp:
            raise KWPSessionError(0x00, "resposta vazia ao StartDiagnosticSession")
        if resp[0] == NEGATIVE:
            nrc = resp[2] if len(resp) > 2 else 0x00
            raise KWPSessionError(nrc, f"StartDiagnosticSession recusado NRC 0x{nrc:02X}")
        if resp[0] != POSITIVE_START:
            raise KWPSessionError(0x00, f"resposta inesperada: {resp.hex()}")
        self.active = True

    def keep_alive(self) -> None:
        if not self.active:
            raise KWPSessionError(0x00, "sessão KWP inativa")
        resp = self.device.send_recv(bytes([SERVICE_TESTER_PRESENT]), timeout_ms=self.timeout_ms)
        if resp and resp[0] == NEGATIVE:
            nrc = resp[2] if len(resp) > 2 else 0x00
            self.active = False
            raise KWPSessionError(nrc, f"TesterPresent recusado NRC 0x{nrc:02X}")

    def stop(self) -> None:
        self.active = False
