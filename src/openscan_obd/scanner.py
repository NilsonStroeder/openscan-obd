"""
Orquestração do scanner — amarra transporte J2534 + decoders OBD-II (Tier A)
+ KWP2000 (Tier B).

Decisão de arquitetura (ver docs/protocol_notes.md): usamos a conexão
J2534 ponto-a-ponto (o próprio J2534 faz o ISO-TP). A enumeração de
módulos é feita SONDANDO cada endereço candidato da tabela NISSAN_MODULES
(reaproveita o método já comprovado em experimental/examples_scan_addresses.py), em vez
de broadcast 0x7DF — mais robusto com a stack que já funciona.

Módulo novo e isolado. A camada de hardware fica aqui; a lógica de
decodificação (testada sem carro) fica em obd2.py e kwp.py.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
from pathlib import Path

from openscan_obd import correlate, kwp, obd2
from openscan_obd.dids import NISSAN_MODULES

DEFAULT_DLL = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"


@contextmanager
def raw_can_connection(dll_path: str, tx: int, rx: int, timeout: float = 2.0, baudrate: int = 500_000):
    """Abre uma conexão J2534 crua (ISO-TP) ponto-a-ponto com o header dado.

    Usa a J2534Connection do udsoncan DIRETAMENTE (sem o Client UDS), pra
    poder mandar bytes crus de OBD-II (modo 03/01/09) e de KWP (0x21).
    """
    from udsoncan.connections import J2534Connection

    conn = J2534Connection(windll=dll_path, rxid=rx, txid=tx, baudrate=baudrate)
    conn.open()
    try:
        yield conn
    finally:
        conn.close()


def _timestamp() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


# ---------------------------------------------------------------------------
# Runners de hardware (usam decoders testados de obd2.py)
# ---------------------------------------------------------------------------

def _request(conn, payload: bytes, timeout: float) -> bytes | None:
    conn.send(payload)
    return conn.wait_frame(timeout=timeout)


def read_vin(conn, timeout: float = 3.0) -> str:
    resp = _request(conn, obd2.build_request(obd2.MODE_VEHICLE_INFO, 0x02), timeout)
    return obd2.decode_vin(resp)  # decode_vin levanta ValueError se resp for None/vazia


def read_live_pid(conn, pid: int, timeout: float = 2.0):
    resp = _request(conn, obd2.build_request(obd2.MODE_LIVE_DATA, pid), timeout)
    return obd2.decode_live_data(resp)


def _hex(resp: bytes | None) -> str:
    return resp.hex() if resp else "sem resposta"


def _engine_obd_report(conn, timeout: float = 2.0) -> list[str]:
    """Le o motor via OBD-II e devolve linhas de relatorio com o hex cru de
    cada resposta ao lado do valor decodificado (ou do erro)."""
    lines: list[str] = []

    def ask(payload: bytes, t: float = timeout) -> bytes | None:
        try:
            return _request(conn, payload, t)
        except Exception as exc:  # noqa: BLE001 — timeout vira linha do relatorio
            lines.append(f"    ({payload.hex()}: {type(exc).__name__}: {exc})")
            return None

    lines.append("  PIDs suportados (bitmaps):")
    for mode, support_pid in [(obd2.MODE_LIVE_DATA, 0x00), (obd2.MODE_LIVE_DATA, 0x20),
                              (obd2.MODE_LIVE_DATA, 0x40), (obd2.MODE_VEHICLE_INFO, 0x00)]:
        resp = ask(obd2.build_request(mode, support_pid))
        try:
            pids = obd2.decode_supported_pids(resp, mode=mode) if resp else None
            detail = " ".join(f"{p:02X}" for p in pids) if pids else "nenhum"
        except ValueError as e:
            detail = f"falhou ({e})"
        lines.append(f"    {mode:02X} {support_pid:02X}: raw={_hex(resp)} -> {detail}")

    resp = ask(obd2.build_request(obd2.MODE_VEHICLE_INFO, 0x02), 3.0)
    try:
        vin = obd2.decode_vin(resp)
    except ValueError as e:
        vin = f"falhou ({e})"
    lines.append(f"  VIN: {vin}  raw={_hex(resp)}")

    for mode, rotulo in [(obd2.MODE_STORED_DTC, "DTCs confirmados"),
                         (obd2.MODE_PENDING_DTC, "DTCs pendentes")]:
        resp = ask(obd2.build_request(mode))
        try:
            dtcs = obd2.decode_dtc_response(resp, mode)
            detail = dtcs if dtcs else "nenhum"
        except ValueError as e:
            detail = f"falhou ({e})"
        lines.append(f"  {rotulo}: {detail}  raw={_hex(resp)}")

    lines.append("  Dados ao vivo:")
    for pid in (0x05, 0x0C, 0x0D, 0x11, 0x42):
        resp = ask(obd2.build_request(obd2.MODE_LIVE_DATA, pid))
        try:
            _, val, unit, nome = obd2.decode_live_data(resp or b"")
            lines.append(f"    {nome}: {val:.1f} {unit}  raw={_hex(resp)}")
        except ValueError as e:
            lines.append(f"    PID 0x{pid:02X}: falhou ({e})  raw={_hex(resp)}")
    return lines


# ---------------------------------------------------------------------------
# Tier A — scan geral OBD-II
# ---------------------------------------------------------------------------

def _probe_bytes(protocol: str) -> bytes:
    # Request barato só pra ver se o módulo responde (positivo OU negativo).
    if protocol == "obd2":
        return obd2.build_request(obd2.MODE_LIVE_DATA, 0x00)  # mode 01 PID 00
    return kwp.build_start_session(0x81)                      # toque de sessao (acorda modulos kwp)


def ping_module(dll_path: str, tx: int, rx: int, protocol: str, timeout: float = 1.5):
    """Tenta falar com um módulo. Retorna (status, detalhe).
    status: "presente" (respondeu algo) | "ausente" (timeout) | "erro".
    """
    from udsoncan.exceptions import TimeoutException

    try:
        with raw_can_connection(dll_path, tx, rx, timeout=timeout) as conn:
            conn.send(_probe_bytes(protocol))
            resp = conn.wait_frame(timeout=timeout)
            if resp:
                return "presente", resp.hex()
            return "ausente", ""
    except TimeoutException as exc:
        return "ausente", f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        return "erro", f"{type(exc).__name__}: {exc}"


def full_scan(dll_path: str = DEFAULT_DLL, out_path: Path | None = None) -> Path:
    """Tier A + enumeração: varre NISSAN_MODULES vendo quem responde, e no
    motor lê DTCs (modo 03 e 07), VIN e alguns PIDs ao vivo. Salva relatório.
    """
    if out_path is None:
        out_path = Path("logs") / f"full_scan_{_timestamp()}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = [f"Scan geral — {dt.datetime.now().isoformat()}", f"DLL: {dll_path}", ""]

    # 1) Enumeração de módulos
    lines.append("=== MÓDULOS (enumeração) ===")
    presentes = []
    for name, m in NISSAN_MODULES.items():
        status, detalhe = ping_module(dll_path, m["tx"], m["rx"], m["protocol"])
        marca = "OK " if status == "presente" else "-- "
        lines.append(f"  {marca}{name:8} tx={hex(m['tx'])} rx={hex(m['rx'])} [{m['protocol']}] {status}  {m['note']}")
        if status == "presente":
            presentes.append(name)
    print("\n".join(lines[-len(NISSAN_MODULES) - 1:]))

    # 2) Dados do motor (Tier A padrão), se presente
    if "engine" in presentes:
        em = NISSAN_MODULES["engine"]
        lines.append("\n=== MOTOR (OBD-II padrão) ===")
        try:
            with raw_can_connection(dll_path, em["tx"], em["rx"]) as conn:
                lines.extend(_engine_obd_report(conn))
        except Exception as e:  # noqa: BLE001
            lines.append(f"  (falha de conexão com o motor: {e!r})")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRelatório salvo em: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Tier B — sonda KWP 0x21
# ---------------------------------------------------------------------------

def kwp_probe(dll_path: str = DEFAULT_DLL, only: str | None = None,
              lid_start: int = 0x00, lid_end: int = 0x20, out_path: Path | None = None) -> Path:
    """Sonda os módulos KWP da tabela: confirma se falam 0x21 e varre LIDs.

    `only` restringe a um módulo (ex: "tcm_cvt"). Salva relatório com os
    LIDs que retornaram dado e uma amostra dos NRC (pra saber se 0x21 é
    suportado mesmo quando nenhum LID devolve dado ainda).
    """
    if out_path is None:
        out_path = Path("logs") / f"kwp_probe_{_timestamp()}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    alvos = {only: NISSAN_MODULES[only]} if only else {
        k: v for k, v in NISSAN_MODULES.items() if v["protocol"] == "kwp"
    }

    lines = [f"Sonda KWP 0x21 — {dt.datetime.now().isoformat()}",
             f"DLL: {dll_path}  | LIDs 0x{lid_start:02X}-0x{lid_end:02X}", ""]

    for name, m in alvos.items():
        lines.append(f"=== {name} (tx={hex(m['tx'])} rx={hex(m['rx'])}) — {m['note']} ===")
        print(f"Sondando {name} ...")
        try:
            with raw_can_connection(dll_path, m["tx"], m["rx"], timeout=1.0) as conn:
                # Passo 1: tentar abrir a sessao de diagnostico certa.
                # (TCM aceita 0x10 mas recusou o subtipo 0x03; o 0x80 nos
                # LIDs sugere "fora da sessao". Descobrimos o subtipo aqui.)
                sess, tentativas = kwp.find_data_session(conn, timeout=1.0)
                if sess is not None:
                    lines.append(f"  Sessao de LEITURA achada: 0x{sess:02X}")
                else:
                    lines.append(f"  Nenhuma sessao liberou o 0x21. Tentativas: {tentativas}")
                    lines.append("  Varredura de LIDs nao executada: sessao de leitura nao confirmada.")
                    lines.append("")
                    continue
                suportado, achados, amostra = kwp.sweep_local_ids(conn, lid_start, lid_end, timeout=1.0, keepalive_every=12)
                lines.append(f"  Serviço 0x21 suportado: {'SIM' if suportado else 'não'}")
                if achados:
                    lines.append(f"  LIDs com DADO ({len(achados)}):")
                    for lid, data_hex in achados:
                        lines.append(f"    LID 0x{lid:02X} -> {data_hex}")
                else:
                    lines.append("  Nenhum LID retornou dado nesta faixa.")
                if amostra:
                    distintos = sorted(set(amostra.values()))
                    lines.append(f"  NRC/erros observados: {distintos}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"  (falha de conexão: {e!r})")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRelatório salvo em: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Caminho B — snapshot de LIDs pra correlacao
# ---------------------------------------------------------------------------

def snapshot_lids(dll_path: str, module_name: str, label: str,
                  lid_start: int = 0x00, lid_end: int = 0xFF,
                  out_path: Path | None = None) -> Path:
    """Tira uma 'foto' dos LIDs de um modulo num estado do carro.

    Abre sessao (descobre o subtipo, inclui 0xC0), varre 0x21 na faixa dada
    e salva {lid: dados} num JSON rotulado. Tire fotos em estados diferentes
    (frio/quente, parado/acelerando) e use 'compare' pra achar o que mudou.
    """
    from openscan_obd.dids import NISSAN_MODULES

    m = NISSAN_MODULES[module_name]
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_path is None:
        safe = "".join(c if c.isalnum() else "_" for c in label)[:30]
        out_path = Path("logs") / f"snapshot_{module_name}_{safe}_{ts}.json"

    print(f"Snapshot '{label}' de {module_name} (tx={hex(m['tx'])} rx={hex(m['rx'])})...")
    with raw_can_connection(dll_path, m["tx"], m["rx"], timeout=1.0) as conn:
        sess, _ = kwp.find_data_session(conn, timeout=1.0)
        if sess is None:
            raise RuntimeError(
                f"Nenhuma sessao de leitura foi confirmada para {module_name}; "
                "snapshot nao foi criado."
            )
        sess_str = f"0x{sess:02X}"
        print(f"  sessao de leitura: {sess_str}")
        _, achados, _ = kwp.sweep_local_ids(conn, lid_start, lid_end, timeout=0.5, keepalive_every=12)
        lids = {f"0x{lid:02X}": data_hex for lid, data_hex in achados}

    snap = correlate.Snapshot(
        module=module_name, label=label,
        timestamp=dt.datetime.now().isoformat(), session=sess_str, lids=lids,
    )
    correlate.save_snapshot(snap, out_path)
    print(f"  {len(lids)} LID(s) com dado. Salvo em: {out_path}")
    return out_path


def compare_snapshots(path_a: Path, path_b: Path, out_path: Path | None = None) -> Path:
    """Compara dois snapshots e mostra/salva os LIDs que mudaram."""
    before = correlate.load_snapshot(path_a)
    after = correlate.load_snapshot(path_b)
    diffs = correlate.diff_snapshots(before, after)
    report = correlate.format_diff_report(before, after, diffs)
    print(report)
    if out_path is None:
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path("logs") / f"compare_{ts}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"Relatorio salvo em: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# Descoberta de modulos — varredura da faixa de diagnostico (0x700-0x7FF)
# ---------------------------------------------------------------------------

# Deslocamentos de resposta observados fora da faixa OBD padrao. +0x20 e o
# padrao Nissan (Leaf/Qashqai; no B16: 0x742->0x762, 0x745->0x765...). +0x10
# foi observado no B16 de teste so no modulo 0x71E->0x72E (can_id_scan
# 2026-10-24); nao e uma regra geral.
ENHANCED_RESPONSE_OFFSETS: tuple[int, ...] = (0x20, 0x10)


def candidate_response_ids(tx: int,
                           offsets: tuple[int, ...] = ENHANCED_RESPONSE_OFFSETS) -> list[int]:
    """IDs de resposta a tentar pra um ID de requisicao, em ordem.

    - Faixa OBD padrao 0x7E0-0x7E7 -> so tx + 8 (ISO 15765-4).
    - Resto -> tx + cada deslocamento de `offsets`, ignorando IDs > 0x7FF.
    """
    if 0x7E0 <= tx <= 0x7E7:
        return [tx + 8]
    return [tx + off for off in offsets if tx + off <= 0x7FF]


def expected_response_id(tx: int) -> int:
    """Primeiro ID de resposta candidato (compatibilidade).

    Fora da faixa OBD padrao o modulo pode responder em outro deslocamento;
    use `candidate_response_ids` pra varrer todos.
    """
    if 0x7E0 <= tx <= 0x7E7:
        return tx + 8
    return tx + 0x20


def discover_modules(dll_path: str = DEFAULT_DLL, tx_start: int = 0x700,
                     tx_end: int = 0x7FF, timeout: float = 0.25,
                     out_path: Path | None = None,
                     response_offsets: tuple[int, ...] = ENHANCED_RESPONSE_OFFSETS) -> Path:
    """Varre a faixa de IDs de requisicao procurando QUALQUER modulo que
    responda, sem depender de uma lista de enderecos chutada.

    Toque = StartDiagnosticSession (0x10 0x81): modulo vivo responde
    positivo (0x50) OU negativo (0x7F 10 xx) — ambos provam presenca.
    Silencio = ausente, em K-line ou respondendo num ID nao testado.

    Fora de 0x7E0-0x7E7, cada tx e tentado em tx+deslocamento pra cada item
    de `response_offsets` (padrao +0x20 e +0x10), parando no primeiro que
    responder. Isso multiplica o tempo da varredura pelo numero de
    deslocamentos.
    """
    if out_path is None:
        out_path = Path("logs") / f"discover_{_timestamp()}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    knock = kwp.build_start_session(0x81)
    from udsoncan.exceptions import TimeoutException

    achados = []
    lines = [f"Descoberta de modulos — {dt.datetime.now().isoformat()}",
             f"DLL: {dll_path} | faixa tx 0x{tx_start:03X}-0x{tx_end:03X}",
             "deslocamentos rx (fora de 0x7E0-0x7E7): "
             + ", ".join(f"+0x{o:02X}" for o in response_offsets),
             f"toque: StartDiagnosticSession {knock.hex()}", ""]

    print(f"Varrendo 0x{tx_start:03X}-0x{tx_end:03X} (pode levar ~1 min)...")
    for tx in range(tx_start, tx_end + 1):
        for rx in candidate_response_ids(tx, response_offsets):
            try:
                with raw_can_connection(dll_path, tx, rx, timeout=timeout) as conn:
                    conn.send(knock)
                    resp = conn.wait_frame(timeout=timeout)
            except TimeoutException:
                continue
            if resp:
                achados.append((tx, rx, resp.hex()))
                msg = f"  RESPONDEU tx=0x{tx:03X} rx=0x{rx:03X} -> {resp.hex()}"
                print(msg)
                lines.append(msg)
                break

    lines.append("")
    lines.append(f"=== {len(achados)} modulo(s) encontrado(s) ===")
    if not achados:
        lines.append("Nenhum respondeu a 0x10. Provavel: modulos em K-line, "
                     "ou o toque/response-id precisa de ajuste.")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(achados)} modulo(s). Relatorio: {out_path}")
    return out_path
