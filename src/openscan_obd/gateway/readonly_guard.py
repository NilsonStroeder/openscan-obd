"""Guarda de somente leitura em volta do adaptador (SDD 5.4, RF7).

Lista de permissão por SID: qualquer coisa fora dela levanta ReadOnlyViolation
ANTES de chegar ao adaptador. Escritas, limpeza de DTC, reset, rotinas e
segurança (04, 11, 14, 27, 2E, 31, 34, 36, 3B...) nunca passam.

O KWP `10` só vale com a subfunção C0 (sessão de diagnóstico já usada nos testes).
`extra_allowed` existe só para o comando de pesquisa `probe-dtc` (SID A3, semântica
desconhecida) e nunca pode conter SIDs de escrita.
"""
from __future__ import annotations

# OBD-II (J1979): dados ao vivo, freeze frame, DTCs, resultados de monitores (06), info do veículo,
# DTCs permanentes. O modo 06 só devolve resultados de testes já feitos pela ECU.
OBD_READ = {0x01, 0x02, 0x03, 0x06, 0x07, 0x09, 0x0A}
# KWP2000: TesterPresent, ReadDataByLocalIdentifier, ReadEcuIdentification, leitura de DTC
KWP_READ = {0x3E, 0x21, 0x1A, 0x13, 0x17, 0x18}
SESSION_SERVICE = 0x10
SESSION_C0 = 0xC0

ALLOWED_SIDS = OBD_READ | KWP_READ
WRITE_SIDS = {0x04, 0x11, 0x14, 0x27, 0x2E, 0x2F, 0x31, 0x34, 0x36, 0x37, 0x3B, 0x3D,
              0x85, 0x28, 0x83, 0x86, 0x87}


class ReadOnlyViolation(PermissionError):
    """Tentativa de enviar um serviço fora da lista de leitura."""


class ReadOnlyDevice:
    def __init__(self, device, extra_allowed: set[int] | None = None) -> None:
        extra = set(extra_allowed or ())
        bad = extra & (WRITE_SIDS | {SESSION_SERVICE})
        if bad:
            raise ValueError(f"extra_allowed não pode conter SIDs de escrita: {sorted(bad)}")
        self._device = device
        self._allowed = ALLOWED_SIDS | extra

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        data = bytes(data)
        if not data:
            raise ReadOnlyViolation("requisição vazia recusada")
        sid = data[0]
        if sid == SESSION_SERVICE:
            if len(data) < 2 or data[1] != SESSION_C0:
                raise ReadOnlyViolation(f"serviço 0x10 só com subfunção C0: {data.hex()}")
        elif sid not in self._allowed:
            raise ReadOnlyViolation(f"serviço 0x{sid:02X} fora da lista de leitura: {data.hex()}")
        return self._device.send_recv(data, timeout_ms=timeout_ms)

    def __getattr__(self, name: str):
        # open, close, set_ids, data_source e o resto da superfície do adaptador
        return getattr(self._device, name)
