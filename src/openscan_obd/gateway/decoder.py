"""Decoders puros de LIDs ECM.

decode_ecm_lid01 implementa as fórmulas do SDD (perfil Sentra B17).
Esses offsets e escalas NÃO foram confirmados no Sentra B16 de teste
(LID 0x01 gravado tem 5 bytes, abaixo do mínimo de 13). Frames curtos
são rejeitados; o resultado não deve ser tratado como leitura validada
neste veículo até haver medição cruzada.
"""
from __future__ import annotations

ECM_LID01_MIN_LEN = 13


def decode_ecm_lid01(raw: bytes) -> dict:
    """Transforma 13+ bytes do LID 0x01 em dict de parâmetros do motor.

    Sem I/O. Levanta ValueError se len(raw) < 13.
    """
    if len(raw) < ECM_LID01_MIN_LEN:
        raise ValueError(
            f"ECM LID 0x01: esperado >= {ECM_LID01_MIN_LEN} bytes, "
            f"recebido {len(raw)}"
        )
    return {
        "rpm": int.from_bytes(raw[0:2], "big") * 12.5,
        "vsp": int.from_bytes(raw[2:4], "big") / 100,
        "tps": raw[4] * 100 / 255,
        "ect": raw[5] - 40,
        "iat": raw[6] - 40,
        "inj_pw": int.from_bytes(raw[7:9], "big") * 0.01,
        "ign_adv": (raw[9] - 128) * 0.5,
        "o2s1": raw[10] * 4.96 / 255,
        "stft": (raw[11] - 128) * 100 / 128,
        "ltft": (raw[12] - 128) * 100 / 128,
        "profile": "sdd_b17_ecm_lid01",
        "verified": False,
    }
