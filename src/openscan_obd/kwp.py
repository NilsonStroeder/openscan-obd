"""
Tier B — KWP2000 (ISO 14230) sobre CAN, serviço 0x21.

A pesquisa (wiki nissanecu + lib gkbus + comportamento do TCM no carro)
estabeleceu que os módulos Nissan desta era falam KWP2000, não UDS. O
serviço central pra ler dados ao vivo é o 0x21 (ReadDataByLocalIdentifier).
Por isso o TCM em 0x7E1 recusou nosso 0x22 (UDS) com ServiceNotSupported.

Este módulo implementa a camada KWP mínima, espelhando o empilhamento do
gkbus (que não serve direto porque o backend dele é SocketCAN/PCAN, não
J2534 — ver docs/protocol_notes.md). Aqui o transporte ISO-TP é feito
pelo próprio J2534 (igual ao resto do projeto).

DECODERS/BUILDERS puros (testáveis sem carro) + um runner fino que usa a
conexão. Novo e isolado: não altera nenhum arquivo existente.
"""
from __future__ import annotations

from dataclasses import dataclass

SERVICE_READ_LOCAL_ID = 0x21      # ReadDataByLocalIdentifier
SERVICE_READ_ECU_ID = 0x1A        # ReadEcuIdentification (alguns módulos)
SERVICE_READ_DTC = 0x18           # ReadDiagnosticTroubleCodesByStatus (KWP)
SERVICE_START_SESSION = 0x10
POSITIVE_OFFSET = 0x40            # resposta positiva = serviço + 0x40
NEGATIVE_MARKER = 0x7F            # resposta negativa: 7F <serviço> <NRC>

# Códigos de resposta negativa (NRC) do KWP2000 — subconjunto relevante.
KWP_NRC = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported / invalidFormat",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x78: "requestCorrectlyReceived-ResponsePending",
}


@dataclass
class KwpResult:
    kind: str          # "positive" | "negative"
    service: int       # serviço ecoado
    data: bytes = b""  # dados (se positive)
    nrc: int | None = None       # código NRC (se negative)
    nrc_name: str = ""           # nome legível do NRC


# Subtipos de sessão a tentar no 0x10. Sabemos (teste 23/10) que o TCM
# ACEITA o serviço 0x10 mas RECUSA o subtipo 0x03 (UDS extended) com
# SubFunctionNotSupported — entao o subtipo certo e outro. KWP2000 usa
# subtipos na faixa 0x8x (fabricante); incluimos tambem 0x01/0x02 (UDS)
# por garantia. Lista curta de proposito (sondagem rapida no carro).
SESSION_TYPES_TO_TRY = [0x81, 0x85, 0x87, 0x88, 0x8A, 0x8B, 0x92, 0xC0, 0x01, 0x02]


def build_start_session(session_type: int) -> bytes:
    """Monta 0x10 <session_type>. Ex: 0x85 -> b'\x10\x85'."""
    return bytes([SERVICE_START_SESSION, session_type])


def discover_session(conn, timeout: float = 1.0):
    """Tenta abrir sessao no modulo testando varios subtipos no 0x10.

    Retorna (session_type_aceito | None, tentativas: dict[subtipo, resultado]).
    Para no primeiro subtipo que der resposta POSITIVA (0x50).
    """
    tentativas = {}
    for st in SESSION_TYPES_TO_TRY:
        conn.send(build_start_session(st))
        try:
            resp = conn.wait_frame(timeout=timeout)
        except TypeError:
            resp = conn.wait_frame()
        except Exception as exc:  # noqa: BLE001
            tentativas[st] = f"sem_resposta/{type(exc).__name__}"
            continue
        try:
            res = parse_response(resp, SERVICE_START_SESSION)
        except ValueError as exc:
            tentativas[st] = f"irreconhecivel/{exc}"
            continue
        if res.kind == "positive":
            tentativas[st] = "ACEITO"
            return st, tentativas
        tentativas[st] = res.nrc_name
    return None, tentativas


def build_read_local_id(lid: int) -> bytes:
    """Monta um request 0x21 <LID>. Ex: lid=0x01 -> b'\\x21\\x01'."""
    return bytes([SERVICE_READ_LOCAL_ID, lid])


def parse_response(resp: bytes, expected_service: int = SERVICE_READ_LOCAL_ID) -> KwpResult:
    """Interpreta uma resposta KWP crua.

    - Positiva: primeiro byte = serviço + 0x40 -> KwpResult(kind="positive", data=resto).
    - Negativa: 0x7F <serviço> <NRC> -> KwpResult(kind="negative", nrc=...).
    Levanta ValueError se a resposta for vazia ou irreconhecível.

    A distinção fina dos NRC é o que torna a sondagem ÚTIL em vez de
    tiro no escuro: um 'serviceNotSupported' (0x11) significa que o módulo
    não fala 0x21; já 'requestOutOfRange' (0x31) ou
    'subFunctionNotSupported' (0x12) significam que 0x21 É suportado, só
    não naquele LID — ou seja, estamos no caminho certo e basta varrer.
    """
    if not resp:
        raise ValueError("resposta vazia")
    if resp[0] == NEGATIVE_MARKER:
        if len(resp) < 3:
            raise ValueError(f"resposta negativa malformada: {resp.hex()}")
        service, nrc = resp[1], resp[2]
        if service != expected_service:
            raise ValueError(
                f"resposta negativa para serviço 0x{service:02X}; "
                f"esperado 0x{expected_service:02X}"
            )
        return KwpResult(
            kind="negative", service=service, nrc=nrc,
            nrc_name=KWP_NRC.get(nrc, f"desconhecido(0x{nrc:02X})"),
        )
    if resp[0] == expected_service + POSITIVE_OFFSET:
        return KwpResult(kind="positive", service=expected_service, data=resp[1:])
    raise ValueError(f"resposta irreconhecível: {resp.hex()}")


def service_is_supported(result: KwpResult) -> bool:
    """Dado o resultado de uma tentativa de 0x21, diz se o serviço 0x21
    é suportado pelo módulo (mesmo que o LID específico não exista).
    """
    if result.kind == "positive":
        return True
    if result.service != SERVICE_READ_LOCAL_ID:
        return False
    # Negativo: só 'serviceNotSupported' derruba o serviço inteiro.
    # Qualquer outro NRC (requestOutOfRange, subFunctionNotSupported,
    # conditionsNotCorrect, securityAccessDenied...) implica que o módulo
    # ENTENDE o 0x21.
    return result.nrc != 0x11


# ---------------------------------------------------------------------------
# Runner (usa hardware; isolado da lógica acima)
# ---------------------------------------------------------------------------

SERVICE_TESTER_PRESENT = 0x3E

# Ordem de sessoes pra DESBLOQUEAR LEITURA (nao so abrir sessao qualquer):
# prioriza as estendidas/fabricante. O Qashqai confirmou que o EPS exige
# 0xC0 pra ler; 0x81 abre sessao mas pode nao liberar 0x21.
SESSION_TYPES_FOR_DATA = [0xC0, 0x87, 0x85, 0x88, 0x8A, 0x8B, 0x92, 0x81, 0x01, 0x02]


def build_tester_present() -> bytes:
    """0x3E 0x00 — mantem a sessao viva durante uma varredura longa."""
    return bytes([SERVICE_TESTER_PRESENT, 0x00])


def find_data_session(conn, test_lids=(0x80, 0xFE, 0x00),
                      sessions=None, timeout: float = 1.0):
    """Acha a sessao sob a qual o 0x21 realmente RETORNA DADO (nao 0x80).

    Pra cada sessao: abre (0x10 sub); se abriu, testa ler alguns LIDs via
    0x21; se algum vier positivo (0x61), essa e a sessao de leitura e a
    conexao ja fica nela. Retorna (session|None, tentativas: dict).
    """
    if sessions is None:
        sessions = SESSION_TYPES_FOR_DATA
    tentativas = {}
    for st in sessions:
        conn.send(build_start_session(st))
        try:
            resp = conn.wait_frame(timeout=timeout)
            res = parse_response(resp, SERVICE_START_SESSION)
        except Exception as exc:  # noqa: BLE001
            tentativas[st] = f"sessao erro/{type(exc).__name__}"
            continue
        if res.kind != "positive":
            tentativas[st] = f"sessao negada/{res.nrc_name}"
            continue
        if not res.data or res.data[0] != st:
            # Alguns módulos Nissan não ecoam o subtipo no positivo — spec
            # KWP2000 não obriga. Loga mas não descarta: testa o 0x21 mesmo assim.
            import warnings
            warnings.warn(
                f"sessao 0x{st:02X}: subtipo ecoado "
                f"0x{res.data[0]:02X} != pedido — módulo pode não ecoar subtipo",
                stacklevel=2,
            )
        # sessao aberta — testa se 0x21 libera dado
        got_data = False
        for lid in test_lids:
            try:
                r = read_local_id(conn, lid, timeout=timeout)
            except Exception:  # noqa: BLE001
                continue
            if r.kind == "positive" and len(r.data) > 1:
                got_data = True
                break
        if got_data:
            tentativas[st] = "ABRIU + 0x21 LIBERADO"
            return st, tentativas
        tentativas[st] = "abriu mas 0x21 ainda negado"
    return None, tentativas


def read_local_id(conn, lid: int, timeout: float = 2.0) -> KwpResult:
    """Envia 0x21 <lid> pela conexão e devolve o KwpResult parseado.

    `conn` precisa expor send(bytes) e wait_frame(timeout) -> bytes.
    """
    conn.send(build_read_local_id(lid))
    try:
        resp = conn.wait_frame(timeout=timeout)
    except TypeError:
        resp = conn.wait_frame()
    result = parse_response(resp, SERVICE_READ_LOCAL_ID)
    if result.kind == "positive" and result.data and result.data[0] != lid:
        # Alguns módulos Nissan não ecoam o LID no primeiro byte do payload —
        # comportamento não mandatório na spec KWP2000. Avisa mas não aborta:
        # descartar o dado causaria falso negativo no sweep de outros módulos.
        import warnings
        warnings.warn(
            f"LID ecoado 0x{result.data[0]:02X} != pedido 0x{lid:02X} "
            f"— módulo pode não ecoar LID no payload",
            stacklevel=2,
        )
    return result


def sweep_local_ids(conn, start: int = 0x00, end: int = 0x20, timeout: float = 1.0, keepalive_every: int = 0):
    """Varre uma faixa de LIDs via 0x21, coletando os que retornam dado.

    Retorna (suportado: bool, achados: list[(lid, data_hex)],
             amostra_nrc: dict[lid, nrc_name]). 'suportado' fica True assim
    que qualquer resposta indicar que o módulo entende 0x21.
    """
    suportado = False
    achados = []
    amostra_nrc = {}
    for i, lid in enumerate(range(start, end + 1)):
        if keepalive_every and i and i % keepalive_every == 0:
            try:
                conn.send(build_tester_present())
                conn.wait_frame(timeout=timeout)
            except Exception:  # noqa: BLE001 — keepalive best-effort
                pass
        try:
            res = read_local_id(conn, lid, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — timeout/erro: registra e segue
            amostra_nrc[lid] = f"sem_resposta/{type(exc).__name__}"
            continue
        if service_is_supported(res):
            suportado = True
        if res.kind == "positive":
            achados.append((lid, res.data.hex()))
        else:
            amostra_nrc[lid] = res.nrc_name
    return suportado, achados, amostra_nrc
