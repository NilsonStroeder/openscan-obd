"""Decoder puro do LID 0x01 do TCM (CVT JF011E/RE0F10A, Sentra B16 de teste).

Somente campos confirmados em docs/scanner_params_tracker.md (medidos com 2+
contrastes independentes). O ATF é a exceção
e sai com sufixo `_estimated`:

- ENG_SPEED: bytes [6,7] big-endian / 8 = rpm  (✅, r=0.998 vs OBD 0x0C)
- VSP: bytes [3] e [4] = km/h 1:1               (✅, r=0.993 vs OBD 0x0D)
- REV: byte [40] == 0x5A em ré                  (✅, 30/30 amostras em R)
- Seletor: nibble alto do byte [54] = marcha    (✅, 112/112: P=1, N=4, D=8, R=2)
- ATF temp: byte [30] pela tabela do ESM é só ESTIMADO (decisão 2026-11-15: sem
  referência independente além da tabela; confirmar com sensor de ATF/estrada);
  byte [9] = 255 - [30] (complemento, NAO é temperatura)

Todo o resto permanece byte cru, sem interpretação (regra do projeto:
não inventar valores de LID sem medição cruzada). Os offsets/escalas do SDD
B17 NÃO se aplicam ao B16.
"""
from __future__ import annotations

TCM_LID01_LEN = 69  # incluindo o eco do LID no byte [0]

# Tabela oficial Nissan ESM — COUNT -> temperatura ATF (docs/cvt_lid01_decoder.md).
ATF_TEMP_TABLE: list[tuple[int, int]] = [
    (4, -30), (47, 20), (83, 40), (124, 60), (169, 85), (243, 200),
]

# Nibble alto de [54] -> marcha (confirmado 2026-11-15, 112/112 payloads).
GEAR_BY_HIGH_NIBBLE: dict[int, str] = {0x1: "P", 0x4: "N", 0x8: "D", 0x2: "R"}


def atf_temp_c(count: int) -> float:
    """Converte COUNT do byte [30] em °C pela tabela ESM (interpolação linear)."""
    if count <= ATF_TEMP_TABLE[0][0]:
        c0, t0 = ATF_TEMP_TABLE[0]
        c1, t1 = ATF_TEMP_TABLE[1]
        return t0 - (c0 - count) * (t1 - t0) / (c1 - c0)
    for (c0, t0), (c1, t1) in zip(ATF_TEMP_TABLE, ATF_TEMP_TABLE[1:]):
        if c0 <= count <= c1:
            return t0 + (count - c0) * (t1 - t0) / (c1 - c0)
    return float(ATF_TEMP_TABLE[-1][1])


def decode_tcm_lid01(b: bytes) -> dict:
    """Decodifica o payload do LID 0x01 do TCM (69 bytes, com eco do LID em [0]).

    Sem I/O. Campos confirmados ganham sufixo de grandeza; o resto vai cru.
    Levanta ValueError se o payload for curto demais.
    """
    if len(b) < TCM_LID01_LEN:
        raise ValueError(f"TCM LID 0x01: esperado {TCM_LID01_LEN} bytes, recebido {len(b)}")
    gear_nibble = b[54] >> 4
    return {
        "ENG_SPEED_rpm": round(((b[6] << 8) | b[7]) / 8.0, 1),
        "VSP_b3": b[3],
        "VSP_b4": b[4],
        "REV_b40": "REVERSE" if b[40] == 0x5A else "NOT_REVERSE",
        "gear": GEAR_BY_HIGH_NIBBLE.get(gear_nibble),
        "gear_raw": f"0x{b[54]:02X}",
        "atf_temp_c_estimated": round(atf_temp_c(b[30]), 1),
        "b30": b[30],
        "b9": b[9],
        "b38_lockup_raw": f"0x{b[38]:02X}",
        "b54": b[54],
        "raw_hex": b.hex(),
    }
