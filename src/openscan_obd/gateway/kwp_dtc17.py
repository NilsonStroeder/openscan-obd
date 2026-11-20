"""KWP2000 SID 0x17 (ReadStatusOfDiagnosticTroubleCodes): decodificação de HIPÓTESE.

Formato (ISO 14230-3): 57 <n> [<hi> <lo> <status>] * n. O mapeamento do código segue SAE J2012
(2 bits altos = P/C/B/U). O byte de status é mantido CRU: seu significado neste TCM é desconhecido.
"""
from __future__ import annotations

_LETTERS = "PCBU"
EMPTY_NOTE = ("lista vazia não prova ausência de falhas: leitura de DTC do CVT ainda não validada")


def dtc_text(code: int) -> str:
    return f"{_LETTERS[(code >> 14) & 3]}{(code >> 12) & 3}{code & 0xFFF:03X}"


def decode_status_of_dtc(resp: bytes) -> dict:
    if len(resp) < 2 or resp[0] != 0x57:
        raise ValueError("resposta não é 0x57 (positiva do SID 0x17)")
    n = resp[1]
    body = resp[2:]
    if len(body) != 3 * n:
        raise ValueError(f"esperados {3 * n} bytes de DTC, recebidos {len(body)}")
    codes = []
    for i in range(n):
        chunk = body[3 * i:3 * i + 3]
        codes.append({"code": dtc_text((chunk[0] << 8) | chunk[1]),
                      "status_byte": f"{chunk[2]:02x}", "raw": chunk.hex()})
    out = {"count": n, "codes": codes, "raw": resp.hex()}
    if n == 0:
        out["note"] = EMPTY_NOTE
    return out
