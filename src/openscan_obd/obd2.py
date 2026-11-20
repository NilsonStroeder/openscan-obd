"""
Tier A — OBD-II padrao (SAE J1979 / ISO 15031) sobre CAN.

Camada generica do scanner: usa so servicos e PIDs padronizados e
publicos, sem nada especifico de fabricante. Suporte a cada PID/servico
varia por veiculo e precisa ser confirmado (ex.: bitmap 01 00).

Este modulo e dividido em duas partes:
  1. DECODERS e BUILDERS puros (sem hardware) — totalmente testaveis
     offline com dados sinteticos. E o nucleo logico.
  2. Um runner fino que usa a conexao J2534 (transport.py) pra enviar os
     requests e coletar respostas. Isolado de proposito, pra logica poder
     ser testada sem carro.

No veiculo de teste (B16) o J1979 Diagnostic Tool do fabricante leu dados
ao vivo; o VIN (modo 09 02) ainda nao foi lido por este codigo.

Referencia de formato: CSS Electronics "OBD2 Explained" e ISO 15765-4.
  - Request funcional broadcast: CAN ID 0x7DF
  - Request fisico: 0x7E0-0x7E7 ; respostas: 0x7E8-0x7EF
  - Resposta = modo do request + 0x40 (01->41, 03->43, 09->49)
  - PCI (1o byte do frame) = tamanho util; multi-frame via ISO-TP (tratado
    nativamente pelo J2534).
"""
from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# PARTE 1 — DECODERS e BUILDERS puros (testaveis sem hardware)
# ---------------------------------------------------------------------------

# Modos de servico OBD-II padrao
MODE_LIVE_DATA = 0x01       # dados ao vivo (PIDs)
MODE_FREEZE_FRAME = 0x02
MODE_STORED_DTC = 0x03      # DTCs confirmados
MODE_CLEAR_DTC = 0x04       # apagar DTCs e dados
MODE_PENDING_DTC = 0x07     # DTCs pendentes
MODE_VEHICLE_INFO = 0x09    # VIN e info do veiculo

_DTC_LETTERS = ("P", "C", "B", "U")  # powertrain, chassis, body, network


def decode_dtc(byte1: int, byte2: int) -> str:
    """Converte 2 bytes num codigo DTC textual (ex: 0x01,0x33 -> 'P0133').

    Formato SAE J2012 / ISO 15031-6:
      bits 7-6 do byte1 = letra (P/C/B/U)
      bits 5-4 do byte1 = 1o digito (0-3)
      bits 3-0 do byte1 = 2o digito (hex)
      byte2 alto/baixo   = 3o e 4o digitos (hex)
    """
    letter = _DTC_LETTERS[(byte1 >> 6) & 0x03]
    d1 = (byte1 >> 4) & 0x03
    d2 = byte1 & 0x0F
    d3 = (byte2 >> 4) & 0x0F
    d4 = byte2 & 0x0F
    return f"{letter}{d1}{d2:X}{d3:X}{d4:X}"


def decode_dtc_list(payload: bytes) -> list[str]:
    """Decodifica uma lista de DTCs a partir do payload de uma resposta de
    modo 03/07 ja sem o byte de resposta positiva.

    Dois formatos sao aceitos, e o tamanho do payload os distingue sem
    ambiguidade:
      - par: so pares de DTC (formato sem contagem);
      - impar: 1 byte com o numero de DTCs seguido de exatamente esse numero
        de pares (formato ISO 15765-4 / CAN). Contagem que nao bate com os
        pares levanta ValueError.

    DTCs 0x0000 (preenchimento/vazio) sao ignorados.
    """
    if len(payload) % 2:
        count, pairs = payload[0], payload[1:]
        if len(pairs) != 2 * count:
            raise ValueError(
                f"Payload de DTC com contagem {count} e {len(pairs)} bytes de pares: "
                f"{payload.hex()}"
            )
        payload = pairs
    dtcs: list[str] = []
    for i in range(0, len(payload), 2):
        b1, b2 = payload[i], payload[i + 1]
        if b1 == 0 and b2 == 0:
            continue
        dtcs.append(decode_dtc(b1, b2))
    return dtcs


def decode_dtc_response(response: bytes | None, mode: int = 0x03) -> list[str]:
    """Valida o byte de resposta positiva (modo + 0x40) e decodifica os DTCs."""
    if not response or response[0] != (mode + 0x40):
        raise ValueError(
            f"Resposta inesperada ao modo {mode:#x}: {response.hex() if response else None}"
        )
    return decode_dtc_list(response[1:])


SUPPORT_PIDS = (0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0)


def decode_supported_pids(response: bytes, mode: int = MODE_LIVE_DATA) -> list[int]:
    """Decodifica um bitmap de PIDs suportados (ex: 41 00 BE 3E B8 11).

    O PID de pedido N (0x00, 0x20, ...) cobre os PIDs N+1 a N+0x20; o bit mais
    significativo do 1o byte corresponde a N+1. Vale para o modo 01 e para o
    modo 09 (PID 00). Retorna os PIDs marcados, em ordem.
    """
    if len(response) != 6 or response[0] != mode + 0x40 or response[1] not in SUPPORT_PIDS:
        raise ValueError(f"Bitmap de PIDs invalido: {response.hex() if response else None}")
    base = response[1]
    bits = int.from_bytes(response[2:6], "big")
    return [base + i + 1 for i in range(32) if bits & (1 << (31 - i))]


@dataclass
class PidDef:
    pid: int
    name: str
    unit: str
    # funcao que recebe os bytes de dado (apos modo+pid) e devolve o valor
    decode: callable
    size: int = 1  # bytes de dado esperados (SAE J1979)


def _u8(d: bytes) -> int:
    return d[0]


# Tabela minima de PIDs de modo 01 comuns e padronizados (publicos).
# Formulas conforme Wikipedia "OBD-II PIDs" / SAE J1979.
PID_TABLE: dict[int, PidDef] = {
    0x04: PidDef(0x04, "Carga do motor (calc.)", "%", lambda d: d[0] * 100 / 255),
    0x05: PidDef(0x05, "Temp. liquido arref.", "C", lambda d: d[0] - 40),
    0x06: PidDef(0x06, "Ajuste combustivel curto prazo B1", "%", lambda d: (d[0] - 128) * 100 / 128),
    0x07: PidDef(0x07, "Ajuste combustivel longo prazo B1", "%", lambda d: (d[0] - 128) * 100 / 128),
    0x0E: PidDef(0x0E, "Avanco de ignicao", "°", lambda d: d[0] / 2 - 64),
    0x0C: PidDef(0x0C, "RPM", "rpm", lambda d: (d[0] * 256 + d[1]) / 4, size=2),
    0x0D: PidDef(0x0D, "Velocidade", "km/h", _u8),
    0x0F: PidDef(0x0F, "Temp. ar admissao", "C", lambda d: d[0] - 40),
    0x10: PidDef(0x10, "Fluxo de ar (MAF)", "g/s", lambda d: (d[0] * 256 + d[1]) / 100, size=2),
    0x11: PidDef(0x11, "Posicao borboleta", "%", lambda d: d[0] * 100 / 255),
    0x14: PidDef(0x14, "Sonda O2 B1S1 (tensao)", "V", lambda d: d[0] / 200, size=2),
    0x15: PidDef(0x15, "Sonda O2 B1S2 (tensao)", "V", lambda d: d[0] / 200, size=2),
    0x1F: PidDef(0x1F, "Tempo desde a partida", "s", lambda d: d[0] * 256 + d[1], size=2),
    0x44: PidDef(0x44, "Lambda comandado", "λ", lambda d: (d[0] * 256 + d[1]) / 32768, size=2),
    0x4C: PidDef(0x4C, "Borboleta comandada", "%", lambda d: d[0] * 100 / 255),
    0x2F: PidDef(0x2F, "Nivel combustivel", "%", lambda d: d[0] * 100 / 255),
    0x42: PidDef(0x42, "Tensao do modulo", "V", lambda d: (d[0] * 256 + d[1]) / 1000, size=2),
    0x43: PidDef(0x43, "Carga absoluta", "%", lambda d: (d[0] * 256 + d[1]) * 100 / 255, size=2),
    0x46: PidDef(0x46, "Temp. ambiente", "C", lambda d: d[0] - 40),
}


def build_request(mode: int, pid: int | None = None) -> bytes:
    """Monta o payload de um request OBD-II (sem o PCI/ISO-TP — o J2534
    cuida do enquadramento). Ex: modo 01 PID 0x0C -> b'\\x01\\x0c'.
    """
    if pid is None:
        return bytes([mode])
    return bytes([mode, pid])


def decode_live_data(response: bytes) -> tuple[int, float | int, str, str]:
    """Decodifica uma resposta de modo 01.

    Espera response comecando com 0x41 (0x01+0x40), seguido do PID e dos
    bytes de dado. Retorna (pid, valor, unidade, nome). Levanta ValueError
    se o PID nao estiver na tabela ou a resposta for malformada.
    """
    if len(response) < 2 or response[0] != 0x41:
        raise ValueError(f"Resposta de modo 01 invalida: {response.hex()}")
    pid = response[1]
    data = response[2:]
    if pid not in PID_TABLE:
        raise ValueError(f"PID 0x{pid:02X} nao esta na tabela")
    d = PID_TABLE[pid]
    if len(data) < d.size:
        raise ValueError(
            f"PID 0x{pid:02X}: esperado {d.size} byte(s) de dado, recebido {len(data)}: "
            f"{response.hex()}"
        )
    return pid, d.decode(data[:d.size]), d.unit, d.name


def decode_vin(response: bytes) -> str:
    """Decodifica a resposta de modo 09 PID 02 (VIN).

    Formato: 0x49 0x02 <NODI> <17 bytes ASCII>. O J2534 ja remonta o
    multi-frame, entao aqui chega o payload completo. Alguns modulos
    intercalam bytes 0x00 de preenchimento no inicio — filtramos nao-ASCII.
    """
    if not response:
        raise ValueError("Resposta de VIN vazia (sem resposta do modulo)")
    if len(response) < 3 or response[0] != 0x49 or response[1] != 0x02:
        raise ValueError(f"Resposta de VIN invalida: {response.hex()}")
    raw = response[3:]  # pula modo, pid, NODI
    chars = [chr(b) for b in raw if 0x20 <= b <= 0x7E]
    vin = "".join(chars).strip()
    if len(vin) != 17:
        raise ValueError(f"VIN com {len(vin)} caracteres (esperado 17): {response.hex()}")
    return vin


# ---------------------------------------------------------------------------
# PARTE 2 — Runner (usa o hardware; isolado da logica acima)
# ---------------------------------------------------------------------------

def read_dtcs(client, mode: int = MODE_STORED_DTC) -> list[str]:
    """Le DTCs de um modulo ja endereçado via a conexao OBD-II.

    `client` precisa expor send(bytes) e wait_frame()->bytes (igual a
    interface de Connection do udsoncan). Retorna lista de codigos.

    OBS: esta funcao e o ponto de integracao com hardware; a logica de
    decodificacao fica em decode_dtc_list (testavel sem carro).
    """
    conn = client
    conn.send(build_request(mode))
    return decode_dtc_response(conn.wait_frame(), mode)
