"""Leitor KWP de LIDs (serviço 0x21). Preserva a resposta crua. Não decodifica.

Tamanhos mínimos de payload pertencem ao decoder/perfil de cada veículo, não
a este leitor. O LID 0x01 do ECM do Sentra B16 de teste devolve 4 bytes de
dados (`61 01 00 1b 00 00`), enquanto o SDD do B17 descreve 13+ bytes; por
isso o leitor não impõe nenhum mínimo por padrão.
"""
from __future__ import annotations

from dataclasses import dataclass

SERVICE_READ_LID = 0x21
POSITIVE_READ = 0x61
NEGATIVE = 0x7F

STATUS_POSITIVE = "positive"
STATUS_NEGATIVE = "negative"
STATUS_UNEXPECTED = "unexpected"


@dataclass(frozen=True)
class LidRead:
    """Resultado de uma leitura 0x21.

    - `positive`: `payload` contém os dados sem o eco do LID.
    - `negative`: `nrc` contém o código de resposta negativa (7F 21 nrc).
    - `unexpected`: resposta vazia, de outro serviço, com eco de outro LID
      ou NRC truncado. `raw` preserva os bytes para diagnóstico.
    """

    lid: int
    status: str
    raw: bytes
    payload: bytes | None = None
    nrc: int | None = None


def rx_id(module_tx: int) -> int:
    """Resposta da faixa OBD padrão 0x7E0-0x7E7 (tx + 8).

    Não vale para módulos fora dessa faixa: no B16 de teste o BCM responde
    em tx+0x20 e o módulo 0x71E em tx+0x10.
    """
    return module_tx + 0x08


def classify_lid_response(resp: bytes | None, lid: int) -> LidRead:
    """Classifica uma resposta crua de `21 <lid>` sem interpretar dados."""
    raw = bytes(resp or b"")
    if not raw:
        return LidRead(lid=lid, status=STATUS_UNEXPECTED, raw=raw)
    if raw[0] == NEGATIVE:
        if len(raw) >= 3 and raw[1] == SERVICE_READ_LID:
            return LidRead(lid=lid, status=STATUS_NEGATIVE, raw=raw, nrc=raw[2])
        return LidRead(lid=lid, status=STATUS_UNEXPECTED, raw=raw)
    if raw[0] == POSITIVE_READ and len(raw) >= 2 and raw[1] == lid:
        return LidRead(lid=lid, status=STATUS_POSITIVE, raw=raw, payload=raw[2:])
    return LidRead(lid=lid, status=STATUS_UNEXPECTED, raw=raw)


def read_lid_detailed(session, lid: int, timeout_ms: int = 200) -> LidRead:
    """Envia `21 <lid>` e devolve o resultado classificado.

    Erros de transporte (timeout, falha da DLL) são propagados ao chamador.
    """
    resp = session.device.send_recv(bytes([SERVICE_READ_LID, lid]), timeout_ms=timeout_ms)
    return classify_lid_response(resp, lid)


def read_lid(
    session,
    module_tx: int,
    lid: int,
    timeout_ms: int = 200,
    min_len: int | None = None,
) -> bytes | None:
    """Lê os bytes crus de um LID, ou None se não houver resposta positiva.

    `module_tx` é mantido por compatibilidade e não altera o comportamento.
    `min_len` é opcional e deve vir do decoder/perfil que vai consumir o
    payload; use `read_lid_detailed` para preservar NRCs.
    """
    del module_tx
    result = read_lid_detailed(session, lid, timeout_ms=timeout_ms)
    if result.status != STATUS_POSITIVE:
        return None
    if min_len is not None and len(result.payload) < min_len:
        return None
    return result.payload
