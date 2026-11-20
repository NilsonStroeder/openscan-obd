"""Leitura KWP 0x18 isolada; não decodifica DTCs específicos do fabricante."""
from __future__ import annotations

from dataclasses import dataclass

SERVICE_READ_DTC = 0x18
POSITIVE_READ_DTC = SERVICE_READ_DTC + 0x40
NEGATIVE_RESPONSE = 0x7F


@dataclass(frozen=True)
class KwpDtcResponse:
    status_mask: int
    raw_response: bytes
    positive: bool
    response_data: bytes = b""
    nrc: int | None = None
    group: int | None = None
    request: bytes = b""


def build_read_dtcs_request(status_mask: int, group: int | None = None) -> bytes:
    """Monta `18 <status>` ou, com `group`, `18 <status> <grupo hi> <grupo lo>`.

    O formato com groupOfDTC de 2 bytes segue ISO 14230-3; qual dos dois os
    módulos do Sentra B16 aceitam ainda NÃO foi validado no veículo. O padrão
    (group=None) mantém o pedido curto usado até agora.
    """
    if not 0 <= status_mask <= 0xFF:
        raise ValueError("status_mask deve estar entre 0x00 e 0xFF")
    if group is None:
        return bytes((SERVICE_READ_DTC, status_mask))
    if not 0 <= group <= 0xFFFF:
        raise ValueError("group deve estar entre 0x0000 e 0xFFFF")
    return bytes((SERVICE_READ_DTC, status_mask)) + group.to_bytes(2, "big")


def read_dtcs_raw(
    session,
    status_mask: int,
    timeout_ms: int = 1000,
    group: int | None = None,
) -> KwpDtcResponse:
    """Envia somente ReadDiagnosticTroubleCodesByStatus e preserva a resposta."""
    if not session.active:
        raise RuntimeError("sessão KWP inativa; leitura DTC cancelada")
    request = build_read_dtcs_request(status_mask, group)
    response = session.device.send_recv(request, timeout_ms=timeout_ms)
    if not response:
        raise ValueError("resposta vazia ao serviço KWP 0x18")
    if response[0] == POSITIVE_READ_DTC:
        return KwpDtcResponse(
            status_mask=status_mask,
            raw_response=response,
            positive=True,
            response_data=response[1:],
            group=group,
            request=request,
        )
    if response[0] == NEGATIVE_RESPONSE:
        if len(response) < 3:
            raise ValueError(f"resposta negativa malformada: {response.hex()}")
        if response[1] != SERVICE_READ_DTC:
            raise ValueError(
                f"resposta negativa para serviço 0x{response[1]:02X}; esperado 0x18"
            )
        return KwpDtcResponse(
            status_mask=status_mask,
            raw_response=response,
            positive=False,
            nrc=response[2],
            group=group,
            request=request,
        )
    raise ValueError(f"resposta KWP 0x18 irreconhecível: {response.hex()}")
