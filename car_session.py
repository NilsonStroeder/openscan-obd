"""
car_session.py — Sessão completa no carro, todas as sondagens extrapoladas.

Nissan Sentra B16 2010 / JF011E / RE0F10A / KWP2000 via J2534 (GODIAG GD101)

Uso:
    .venv\\Scripts\\activate
    python car_session.py [--dll <path>] <comando>

Comandos:
    all          Faz tudo em sequência (recomendado)
    enum         Só enumeração de módulos (quem responde ao ping)
    ecm          Sonda ECM em KWP (10 C0 + sweep 0x00-0xFF)
    bcm          Sonda BCM em KWP
    ipdm         Sonda IPDM em KWP
    eps          Sonda EPS em KWP
    meter        Sonda METER em KWP
    tcm          Snapshot TCM completo + sweep de LIDs desconhecidos
    correlated   Polling simultâneo LID 0x01 TCM + OBD PIDs (RPM/VSP/TPS/ECT)
    field        Captura field tests guiados (instructions no terminal)

Segurança:
    - Apenas 0x10 (StartDiagnosticSession) + 0x21 (ReadDataByLocalIdentifier)
    - Nunca tenta 0x27 SecurityAccess
    - Nunca escreve (0x2E/0x31)
    - NUNCA descompila nada, NUNCA inventa algoritmos seed/key
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

DEFAULT_DLL = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"

MODULES = {
    "ecm":   {"tx": 0x7E0, "rx": 0x7E8, "name": "ECM (Motor)",  "confirmed": True,
               "note": "OBD-II ok; KWP 10 C0 aceito (2026-10-24); LID 0x01 = 4 bytes de dados"},
    "tcm":   {"tx": 0x7E1, "rx": 0x7E9, "name": "TCM CVT",      "confirmed": True,
               "note": "KWP 10 C0 ok; 33 LIDs mapeados"},
    "eps":   {"tx": 0x742, "rx": 0x762, "name": "EPS",          "confirmed": True,
               "note": "Respondeu ao discover; nunca lido"},
    "meter": {"tx": 0x743, "rx": 0x763, "name": "METER",        "confirmed": True,
               "note": "Respondeu ao discover; nunca lido"},
    "bcm":   {"tx": 0x745, "rx": 0x765, "name": "BCM",          "confirmed": True,
               "note": "Respondeu ao discover; nunca lido"},
    "ipdm":  {"tx": 0x74D, "rx": 0x76D, "name": "IPDM",         "confirmed": True,
               "note": "Respondeu ao discover; nunca lido"},
    # "confirmed" = o par tx/rx responde; nao confirma a identidade do modulo.
    "abs":   {"tx": 0x740, "rx": 0x760, "name": "ABS/VDC",      "confirmed": False,
               "note": "Nao respondeu em 0x740/0x760; pode ser o modulo 0x71E (nao verificado)"},
    "unk71e":{"tx": 0x71E, "rx": 0x72E, "name": "Modulo 0x71E (identidade desconhecida)", "confirmed": True,
               "note": "can_scan 20261024: responde 50C0 em tx+0x10; ABS/VDC e hipotese"},
    "airbag":{"tx": 0x752, "rx": 0x772, "name": "SRS/Airbag",   "confirmed": False,
               "note": "Nao respondeu ao can_scan — ID pode estar errado"},
    "hvac":  {"tx": 0x744, "rx": 0x764, "name": "HVAC",         "confirmed": False,
               "note": "Nao respondeu ao can_scan — ID pode estar errado"},
}

SESSION_TYPES = [0xC0, 0x87, 0x85, 0x88, 0x8A, 0x8B, 0x92, 0x81, 0x01, 0x02]

OBD_PIDS = {0x0C: "RPM", 0x0D: "VSP", 0x11: "TPS", 0x05: "ECT"}

# Tabela ATF TEMP COUNT (ESM). NAO usar em [9]: a auditoria de 2026-11-05
# mostrou [9] invertido ([30] = 255-[9]); a aplicacao a [30] e hipotese.
# Mantida so como referencia; decode_lid01_live nao a usa.
ATF_TABLE = [(4,-30),(47,20),(83,40),(124,60),(169,85),(243,200)]

def atf_count_to_c(count):
    if count <= ATF_TABLE[0][0]: return float(ATF_TABLE[0][1])
    if count >= ATF_TABLE[-1][0]: return float(ATF_TABLE[-1][1])
    for i in range(len(ATF_TABLE)-1):
        c0,t0 = ATF_TABLE[i]; c1,t1 = ATF_TABLE[i+1]
        if c0 <= count <= c1:
            return t0 + (t1-t0)*(count-c0)/(c1-c0)
    return float("nan")

def ts():
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")

def log_path(tag):
    p = Path("logs") / f"{tag}_{ts()}.json"
    p.parent.mkdir(exist_ok=True)
    return p

def print_header(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")

def print_sub(title):
    print(f"\n--- {title} ---")

def get_conn(dll, tx, rx, timeout=2.0):
    from udsoncan.connections import J2534Connection
    conn = J2534Connection(windll=dll, rxid=rx, txid=tx, baudrate=500_000)
    conn.open()
    return conn

def send_recv(conn, data, timeout=2.0):
    conn.send(data)
    try:
        return conn.wait_frame(timeout=timeout)
    except Exception:
        return None

def kwp_session(conn, timeout=1.5):
    from openscan_obd.kwp import build_start_session, parse_response, SERVICE_START_SESSION
    tentativas = {}
    for st in SESSION_TYPES:
        resp = send_recv(conn, build_start_session(st), timeout)
        if resp is None:
            tentativas[st] = "sem_resposta"; continue
        try:
            res = parse_response(resp, SERVICE_START_SESSION)
        except ValueError as e:
            tentativas[st] = f"parse_error/{e}"; continue
        if res.kind == "positive":
            tentativas[st] = "ACEITO"
            return st, tentativas
        tentativas[st] = res.nrc_name
    return None, tentativas

def kwp_read_lid(conn, lid, timeout=2.0):
    from openscan_obd.kwp import build_read_local_id, parse_response, SERVICE_READ_LOCAL_ID
    resp = send_recv(conn, build_read_local_id(lid), timeout)
    if resp is None: return None
    try:
        res = parse_response(resp, SERVICE_READ_LOCAL_ID)
        if res.kind == "positive": return res.data
    except ValueError:
        pass
    return None

def kwp_keepalive(conn):
    conn.send(bytes([0x3E, 0x00]))
    try: conn.wait_frame(timeout=0.5)
    except Exception: pass

def decode_lid01_live(b):
    """Campos do LID 0x01 do TCM (B16) para exibicao em campo.

    So os campos com sufixo de grandeza sao confirmados (docs/
    scanner_params_tracker.md, 2026-11-05): ENG_SPEED_rpm ([6,7]/8),
    VSP_b3/VSP_b4 (km/h 1:1) e REV_b40 (0x5A = re). Todo o resto e byte cru
    sem interpretacao; ATF [9]/[30], STM [36,37], seletor [23-25]/[54],
    lock-up [38] e [41]/[42] sao hipoteses nao verificadas.
    """
    if len(b) < 69: return {"erro": f"payload curto: {len(b)} bytes"}
    return {
        "ENG_SPEED_rpm":  round(((b[6]<<8)|b[7])/8.0, 1),
        "VSP_b3":         b[3], "VSP_b4": b[4],
        "REV_b40":        "REVERSE" if b[40] == 0x5A else "NOT_REVERSE",
        "b9": b[9], "b30": b[30],
        "b11": b[11], "b12": b[12],
        "b23": b[23], "b24": b[24], "b25": b[25],
        "b36_37_word":    (b[36]<<8)|b[37],
        "b38": b[38], "b41": b[41], "b42": b[42],
        "b44_45_word_le": (b[44]|(b[45]<<8)),
        "b5": b[5], "b10": b[10], "b15": b[15], "b18": b[18],
        "b19": b[19], "b20": b[20], "b21": b[21], "b22": b[22],
        "b26": b[26], "b27": b[27], "b28": b[28],
        "b39": b[39], "b54": b[54],
        "b48_67_hex": b[48:68].hex(),
    }

def probe_module_full(dll, key, lid_start=0x00, lid_end=0xFF, keepalive_every=20):
    m = MODULES[key]
    print_sub(f"{m['name']} (tx={hex(m['tx'])} rx={hex(m['rx'])})")
    print(f"  Nota: {m['note']}")
    resultado = {
        "module": key, "name": m["name"], "tx": hex(m["tx"]), "rx": hex(m["rx"]),
        "session_aberta": None, "session_tentativas": {},
        "lids_com_dado": {}, "lids_negados": {}, "lids_sem_resposta": [],
        "timestamp": dt.datetime.now().isoformat(),
    }
    try:
        conn = get_conn(dll, m["tx"], m["rx"])
    except Exception as e:
        print(f"  ERRO abrindo conexão: {e}")
        resultado["erro_conexao"] = str(e)
        return resultado
    try:
        session, tentativas = kwp_session(conn)
        resultado["session_tentativas"] = {hex(k): v for k,v in tentativas.items()}
        if session is None:
            print(f"  Nenhuma sessão aceita. Tentativas: {tentativas}")
            return resultado
        resultado["session_aberta"] = hex(session)
        print(f"  Sessão aberta: 0x{session:02X}")
        print(f"  Varrendo LIDs 0x{lid_start:02X}–0x{lid_end:02X}...")
        for i, lid in enumerate(range(lid_start, lid_end+1)):
            if keepalive_every and i and i % keepalive_every == 0:
                kwp_keepalive(conn)
                print(f"    [{i}/{lid_end-lid_start+1}] LID 0x{lid:02X}...", end="\r")
            data = kwp_read_lid(conn, lid)
            if data is None:
                resultado["lids_sem_resposta"].append(hex(lid))
            elif data == b"":
                resultado["lids_negados"][hex(lid)] = "empty"
            else:
                resultado["lids_com_dado"][hex(lid)] = data.hex()
                print(f"  LID 0x{lid:02X}: {data.hex()[:64]}{'...' if len(data)>32 else ''}")
    except Exception as e:
        print(f"  ERRO durante sweep: {e}")
        resultado["erro_sweep"] = str(e)
    finally:
        try: conn.close()
        except Exception: pass
    n = len(resultado["lids_com_dado"])
    print(f"  Resultado: {n} com dado | {len(resultado['lids_negados'])} negados | {len(resultado['lids_sem_resposta'])} sem resposta")
    return resultado

TCM_ALL_LIDS = (list(range(0x00, 0x04)) + list(range(0x10, 0x22)) +
                [0x40, 0x60] + list(range(0x80, 0x85)) + [0xF0, 0xF1, 0xFE, 0xFF])

def snapshot_tcm_all(dll, label="completo"):
    print_header(f"SNAPSHOT TCM — TODOS OS LIDs ({label})")
    conn = None
    snapshot = {"label": label, "timestamp": dt.datetime.now().isoformat(), "lids": {}}
    try:
        conn = get_conn(dll, 0x7E1, 0x7E9, timeout=2.0)
        session, _ = kwp_session(conn)
        if session is None:
            print("  Sessão KWP não aberta.")
            return log_path(f"tcm_snapshot_{label}_FAILED")
        print(f"  Sessão: 0x{session:02X}")
        for i, lid in enumerate(TCM_ALL_LIDS):
            if i and i % 10 == 0: kwp_keepalive(conn)
            data = kwp_read_lid(conn, lid, timeout=2.0)
            snapshot["lids"][hex(lid)] = data.hex() if data else None
            print(f"  LID 0x{lid:02X}: {len(data)} bytes  {data.hex()[:32]}" if data else f"  LID 0x{lid:02X}: sem dado")
        print("\n  Varredura complementar (LIDs nao catalogados)...")
        known = set(TCM_ALL_LIDS)
        for lid in range(0x00, 0x100):
            if lid in known: continue
            data = kwp_read_lid(conn, lid, timeout=0.5)
            if data:
                snapshot["lids"][hex(lid)] = data.hex()
                print(f"  NOVO LID 0x{lid:02X}: {len(data)} bytes  {data.hex()[:32]}")
            if lid % 20 == 0: kwp_keepalive(conn)
    except KeyboardInterrupt:
        print("\n  Interrompido.")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    out = log_path(f"tcm_snapshot_{label}")
    out.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"\n  Snapshot TCM salvo: {out}")
    return out

FIELD_TEST_STEPS = [
    ("P_frio",        "Carro acabou de ligar — seletor em P, sem pisar no acelerador"),
    ("P_quente",      "Carro quente (ATF ~60 graus) — seletor em P, sem pisar"),
    ("N_idle",        "Seletor em N, sem pisar"),
    ("D_idle",        "Seletor em D, pé no freio, parado"),
    ("R_parado",      "Seletor em R, pé no freio, parado — CONFIRMA b[40]=REVERSE"),
    ("D_rpm1000",     "D, freio, acelerador para ~1000 RPM"),
    ("D_rpm2000",     "D, freio, acelerador para ~2000 RPM"),
    ("D_rpm3000",     "D, freio, acelerador para ~3000 RPM"),
    ("D_arranque",    "D, SOLTAR O FREIO, arrancada suave (0 a 20 km/h)"),
    ("cruising_40",   "D, cruzeiro constante 40 km/h — manter 10s"),
    ("cruising_60",   "D, cruzeiro constante 60 km/h — manter 10s"),
    ("cruising_80",   "D, cruzeiro constante 80 km/h — manter 10s"),
    ("cruising_100",  "D, cruzeiro 100 km/h, throttle MINIMO — aguardar lock-up (~30s)"),
    ("tcc_100",       "D, 100 km/h, lock-up engajado, throttle minimo — CONFIRMA b[42]=0"),
    ("accel_P_leve",  "P, ACELERE LEVEMENTE sem sair do lugar — APP em b[48-67]"),
    ("accel_P_pleno", "P, FUNDO no acelerador por 2s — APP + STM salvo"),
    ("decel_100_0",   "D, 100 a 0 km/h em motor braking — STM e b[42] em decel"),
]

def guided_field_tests(dll):
    print_header("FIELD TESTS GUIADOS — LID 0x01 TCM")
    print("  Siga as instruções e pressione ENTER quando no estado pedido.\n")
    captures = {}
    conn = None
    try:
        conn = get_conn(dll, 0x7E1, 0x7E9, timeout=2.0)
        session, tentativas = kwp_session(conn)
        if session is None:
            print(f"  Sessão KWP nao aberta. Tentativas: {tentativas}")
            return log_path("field_tests_FAILED")
        print(f"  Sessão KWP: 0x{session:02X}\n")
        for label, instrucao in FIELD_TEST_STEPS:
            print(f"\n[{label}]")
            print(f"  -> {instrucao}")
            input("  Pressione ENTER quando pronto...")
            amostras = []
            for _ in range(5):
                d = kwp_read_lid(conn, 0x01, timeout=1.0)
                if d: amostras.append(d)
                time.sleep(0.1)
            kwp_keepalive(conn)
            if not amostras:
                print(f"  Sem resposta para {label}")
                captures[label] = None
                continue
            payload = amostras[len(amostras)//2]
            dec = decode_lid01_live(payload) if len(payload) >= 69 else {}
            captures[label] = {"hex": payload.hex(), "decoded": dec, "n_amostras": len(amostras)}
            print(f"  Capturado ({len(payload)} bytes)")
            if dec:
                print(f"     ENG_SPEED={dec.get('ENG_SPEED_rpm')} RPM  "
                      f"VSP_b3={dec.get('VSP_b3')}  b36_37={dec.get('b36_37_word')}  "
                      f"b40={dec.get('REV_b40')}  b42={dec.get('b42')}  b38=0x{dec.get('b38', 0):02X}")
    except KeyboardInterrupt:
        print("\n  Interrompido.")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    out = log_path("field_tests")
    out.write_text(json.dumps(captures, indent=2, default=str), encoding="utf-8")
    print(f"\n  Field tests salvos: {out}")
    return out

def _obd_decode_pid(pid, data):
    """Decodifica uma resposta de modo 01 com os decoders de obd2.py.

    Retorna o valor arredondado a 0.1, ou None se nao houver resposta, se a
    resposta nao for `41 <pid> ...` ou se faltar dado. O hex cru e guardado
    a parte pelo chamador.
    """
    from openscan_obd import obd2
    if not data:
        return None
    data = bytes(data)
    # Tolera bytes antes de `41 <pid>` (comportamento da versao anterior; o
    # formato exato devolvido pelo GD101 nao foi registrado — o hex cru agora
    # e gravado em obd_<nome>_raw para conferir).
    start = data.find(bytes([0x41, pid]))
    if start < 0:
        return None
    try:
        got_pid, value, _unit, _name = obd2.decode_live_data(data[start:])
    except ValueError:
        return None
    if got_pid != pid:
        return None
    return round(float(value), 1)


def correlated_poll(dll, duration_s=120.0, interval_s=0.5, label="correlated"):
    """Polling correlacionado TCM KWP + ECM OBD com conexao alternada (single-channel).

    Compativel com GD101 e qualquer J2534 basico que nao suporta dois canais simultaneos.
    Estrategia: abre TCM, le LID 0x01, fecha; abre ECM, le PIDs, fecha. Repete.
    Overhead por ciclo: ~200-300ms extra vs paralelo — ok para correlacao em segundos.

    Tempos por registro (segundos desde o inicio, relogio monotonic):
      t       inicio do ciclo
      t_tcm   resposta do LID 0x01 do TCM recebida
      t_<PID> resposta de cada PID OBD recebida (t_RPM, t_VSP, t_TPS, t_ECT)
    A diferenca t_VSP - t_tcm mostra quanto o OBD e o TCM de uma mesma linha
    estao defasados (as leituras sao em sequencia, nao simultaneas).
    """
    print_header(f"POLLING CORRELACIONADO ({duration_s:.0f}s)")
    print("  LID 0x01 TCM + OBD PIDs — conexao alternada (single-channel).")
    print("  Varie velocidade, cruzeiro, freadas. Ctrl+C salva o capturado.\n")
    records = []
    out_json = log_path(f"correlated_{label}")
    out_csv  = out_json.with_suffix(".csv")
    tcm_session = None
    t_start = time.monotonic()
    started_at = dt.datetime.now().astimezone().isoformat()

    def stamp():
        return round(time.monotonic() - t_start, 3)

    i = 0
    try:
        while (time.monotonic() - t_start) < duration_s:
            t_iter = time.monotonic()
            rec = {"t": round(t_iter - t_start, 3), "i": i}

            # --- TCM: abrir, ler LID 0x01, fechar ---
            conn_tcm = None
            try:
                conn_tcm = get_conn(dll, 0x7E1, 0x7E9, timeout=1.5)
                if tcm_session is None:
                    tcm_session, _ = kwp_session(conn_tcm)
                    if tcm_session is None:
                        print("  Sessao KWP TCM nao aberta. Abortando.")
                        break
                    print(f"  Sessao TCM: 0x{tcm_session:02X}")
                else:
                    from openscan_obd.kwp import build_start_session
                    send_recv(conn_tcm, build_start_session(tcm_session), timeout=1.0)
                lid01_raw = kwp_read_lid(conn_tcm, 0x01, timeout=0.8)
                rec["t_tcm"] = stamp()
                if lid01_raw and len(lid01_raw) >= 69:
                    rec["lid01_hex"] = lid01_raw.hex()
                    rec["lid01"] = decode_lid01_live(lid01_raw)
                else:
                    rec["lid01_hex"] = None
            except Exception as e:
                rec["lid01_hex"] = None
                rec["tcm_err"] = str(e)
            finally:
                if conn_tcm:
                    try: conn_tcm.close()
                    except Exception: pass

            # --- ECM: abrir, ler PIDs OBD, fechar ---
            # Tenta primeiro endereco fisico 0x7E0->0x7E8; alguns ECMs Nissan CAN
            # pre-UDS respondem Mode 0x01 apenas via broadcast funcional 0x7DF.
            # Se todos os PIDs voltarem null com o fisico, o fallback 0x7DF entra.
            conn_ecm = None
            try:
                conn_ecm = get_conn(dll, 0x7E0, 0x7E8, timeout=1.5)
                results_phys = {}
                raw_phys = {}
                times_phys = {}
                for pid, name in OBD_PIDS.items():
                    shortname = name.split()[0]
                    resp = send_recv(conn_ecm, bytes([0x01, pid]), 0.8)
                    times_phys[shortname] = stamp()
                    results_phys[shortname] = _obd_decode_pid(pid, resp)
                    raw_phys[shortname] = resp.hex() if resp else None
                conn_ecm.close(); conn_ecm = None

                # Fallback 0x7DF se todos os PIDs fisicos retornaram None
                if all(v is None for v in results_phys.values()):
                    conn_ecm = get_conn(dll, 0x7DF, 0x7E8, timeout=1.5)
                    for pid, name in OBD_PIDS.items():
                        shortname = name.split()[0]
                        resp = send_recv(conn_ecm, bytes([0x01, pid]), 0.8)
                        times_phys[shortname] = stamp()
                        results_phys[shortname] = _obd_decode_pid(pid, resp)
                        raw_phys[shortname] = resp.hex() if resp else None
                    rec["obd_via"] = "broadcast_7DF"
                else:
                    rec["obd_via"] = "physical_7E0"

                for k, v in results_phys.items():
                    rec[f"obd_{k}"] = v
                    rec[f"obd_{k}_raw"] = raw_phys.get(k)
                    rec[f"t_{k}"] = times_phys.get(k)
            except Exception as e:
                rec["ecm_err"] = str(e)
            finally:
                if conn_ecm:
                    try: conn_ecm.close()
                    except Exception: pass

            records.append(rec)
            if i % 5 == 0:
                elapsed = time.monotonic() - t_start
                lid = rec.get("lid01") or {}
                print(f"  [{elapsed:.1f}s] #{i:4d} | "
                      f"RPM={str(rec.get('obd_RPM','?')):>6} "
                      f"VSP={str(rec.get('obd_VSP','?')):>4}km/h | "
                      f"b3={str(lid.get('VSP_b3','?')):>4} "
                      f"ENG={str(lid.get('ENG_SPEED_rpm','?')):>6}rpm "
                      f"b9={str(lid.get('b9','?')):>3} b30={str(lid.get('b30','?')):>3}", end="\r")
            i += 1
            dt_iter = time.monotonic() - t_iter
            if dt_iter < interval_s:
                time.sleep(interval_s - dt_iter)
    except KeyboardInterrupt:
        print("\n  Interrompido pelo usuario.")
    out_json.write_text(json.dumps({
        "label": label,
        "started_at": started_at,
        "time_base": "segundos desde started_at (monotonic); t_tcm e t_<PID> = resposta recebida",
        "records": records,
    }, indent=2), encoding="utf-8")
    if records:
        headers = ["t","t_tcm","t_RPM","t_VSP","t_TPS","t_ECT",
                   "obd_RPM","obd_VSP","obd_TPS","obd_ECT",
                   "ENG_SPEED_rpm","VSP_b3","VSP_b4","b11","b12",
                   "b36_37_word","b38","REV_b40","b41","b42","b9","b30","b18","b19","b54"]
        with out_csv.open("w", encoding="utf-8") as f:
            f.write(",".join(headers)+"\n")
            for r in records:
                lid = r.get("lid01") or {}
                row = [r["t"],r.get("t_tcm"),r.get("t_RPM"),r.get("t_VSP"),r.get("t_TPS"),r.get("t_ECT"),
                       r.get("obd_RPM"),r.get("obd_VSP"),r.get("obd_TPS"),r.get("obd_ECT"),
                       lid.get("ENG_SPEED_rpm"),lid.get("VSP_b3"),lid.get("VSP_b4"),
                       lid.get("b11"),lid.get("b12"),
                       lid.get("b36_37_word"),lid.get("b38"),lid.get("REV_b40"),
                       lid.get("b41"),lid.get("b42"),lid.get("b9"),lid.get("b30"),
                       lid.get("b18"),lid.get("b19"),lid.get("b54")]
                f.write(",".join(str(v) if v is not None else "" for v in row)+"\n")
    print(f"\n  {len(records)} registros: {out_json.name} | {out_csv.name}")
    return out_json


def ecm_lid_sweep(dll, lids=None):
    """Varre LIDs específicos do ECM em sessão 0xC0 e salva o hex bruto.

    lids: lista de ints; default = [0x01..0x09, 0x20, 0x83]
    Não tenta LIDs que exijam SecurityAccess — só 0x21 puro.
    """
    if lids is None:
        lids = list(range(0x01, 0x0A)) + [0x20, 0x83]
    print_header("ECM LID SWEEP")
    print(f"  LIDs alvo: {[hex(x) for x in lids]}")
    resultado = {
        "modulo": "ECM", "tx": hex(0x7E0), "rx": hex(0x7E8),
        "session": None, "lids": {},
        "timestamp": dt.datetime.now().isoformat(),
    }
    conn = None
    try:
        conn = get_conn(dll, 0x7E0, 0x7E8, timeout=2.0)
        session, tentativas = kwp_session(conn)
        resultado["session_tentativas"] = {hex(k): v for k,v in tentativas.items()}
        if session is None:
            print("  Nenhuma sessão ECM aceita.")
            return resultado
        resultado["session"] = hex(session)
        print(f"  Sessão ECM aberta: 0x{session:02X}")
        for lid in lids:
            data = kwp_read_lid(conn, lid, timeout=1.5)
            if data is None:
                resultado["lids"][hex(lid)] = None
                print(f"  LID 0x{lid:02X}: sem resposta")
            else:
                resultado["lids"][hex(lid)] = data.hex()
                print(f"  LID 0x{lid:02X}: {data.hex()}")
    except Exception as e:
        print(f"  ERRO: {e}")
        resultado["erro"] = str(e)
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    out = log_path(f"ecm_lid_sweep")
    out.write_text(json.dumps(resultado, indent=2), encoding="utf-8")
    print(f"  Salvo: {out}")
    return resultado


def reverse_state_capture(dll, n_samples=30, interval_s=1.0):
    """Captura estado do TCM LID 0x01 com seletor em R.

    Instrui o usuário a colocar em ré e registra n_samples leituras.
    Salva JSON com os payloads raw para análise de b[23-25], b[40].
    """
    print_header("CAPTURA EM MARCHA RÉ")
    print("  Motor ligado, carro PARADO.")
    print("  Aguardando você colocar o seletor em R...")
    input("  [ENTER] quando estiver em R → ")
    print(f"  Coletando {n_samples} amostras em R (intervalo {interval_s}s)...")
    registros = []
    conn = None
    try:
        conn = get_conn(dll, 0x7E1, 0x7E9, timeout=2.0)
        session, _ = kwp_session(conn)
        if session is None:
            print("  Sessão TCM não aberta. Abortando.")
            return None
        for i in range(n_samples):
            t = time.monotonic()
            raw = kwp_read_lid(conn, 0x01, timeout=1.5)
            rec = {
                "i": i,
                "t": round(t, 3),
                "raw_hex": raw.hex() if raw else None,
                "decoded": decode_lid01_live(raw) if (raw and len(raw) >= 69) else None,
            }
            registros.append(rec)
            gear = rec["decoded"]["b41"] if rec["decoded"] else "?"
            rev = rec["decoded"]["REV_b40"] if rec["decoded"] else "?"
            print(f"  [{i+1:02d}/{n_samples}] b41={gear} REV={rev}", end="\r")
            dt_iter = time.monotonic() - t
            if dt_iter < interval_s:
                time.sleep(interval_s - dt_iter)
    except Exception as e:
        print(f"\n  ERRO: {e}")
    finally:
        if conn:
            try: conn.close()
            except Exception: pass
    print(f"\n  {len(registros)} amostras coletadas.")
    print("  Volte o seletor para P antes de continuar.")
    input("  [ENTER] quando estiver de volta em P → ")
    out = log_path("reverse_state")
    out.write_text(json.dumps({"registros": registros}, indent=2), encoding="utf-8")
    print(f"  Salvo: {out}")
    return registros


def module_quick_probe(dll, keys=None):
    """Tenta sessão KWP nos módulos listados e registra quem responde.

    Diferente do probe_module_full, NÃO varre todos os LIDs —
    só confirma se a sessão abre e lê LID 0x01 como amostra.
    Rápido (~3s por módulo).
    """
    if keys is None:
        keys = ["bcm", "ipdm", "eps", "meter", "unk71e", "abs", "airbag", "hvac"]
    print_header("PROBE RÁPIDO DE MÓDULOS")
    resultados = {}
    for key in keys:
        m = MODULES[key]
        print(f"  {key:8} tx={hex(m['tx'])} rx={hex(m['rx'])}  {m['name']}...", end=" ")
        conn = None
        try:
            conn = get_conn(dll, m["tx"], m["rx"], timeout=1.5)
            session, tentativas = kwp_session(conn)
            if session is None:
                print("sem sessão")
                resultados[key] = {"status": "sem_sessao", "tentativas": {hex(k): v for k,v in tentativas.items()}}
            else:
                lid01 = kwp_read_lid(conn, 0x01, timeout=1.5)
                resultados[key] = {
                    "status": "OK",
                    "session": hex(session),
                    "lid01_hex": lid01.hex() if lid01 else None,
                }
                print(f"OK sessão={hex(session)} lid01={'OK' if lid01 else 'null'}")
        except Exception as e:
            resultados[key] = {"status": "erro", "detail": str(e)}
            print(f"ERRO: {e}")
        finally:
            if conn:
                try: conn.close()
                except Exception: pass
    out = log_path("module_quick_probe")
    out.write_text(json.dumps(resultados, indent=2), encoding="utf-8")
    print(f"  Salvo: {out}")
    return resultados


def multi_module_lid_sweep(dll, keys=None, lids=None):
    """Sweep completo de LIDs nos modulos confirmados (BCM, IPDM, EPS).

    Varre cada LID de 0x01 a 0x60 em cada modulo, registra hex de quem responde.
    Seguro: so usa 0x10 (StartDiagnosticSession) + 0x21 (ReadDataByLocalIdentifier).
    Nunca tenta SecurityAccess (0x27) nem escrita.

    Resultado salvo em logs/multi_lid_sweep_<ts>.json
    """
    if keys is None:
        keys = ["bcm", "ipdm", "eps", "meter"]
    if lids is None:
        lids = list(range(0x01, 0x61))  # 0x01 a 0x60

    print_header("SWEEP DE LIDs — MULTI-MODULO")
    print(f"  Modulos: {keys}")
    print(f"  LIDs: 0x{lids[0]:02X} a 0x{lids[-1]:02X} ({len(lids)} LIDs)")
    resultados = {}

    for key in keys:
        m = MODULES.get(key)
        if m is None:
            print(f"  {key}: nao encontrado em MODULES — pulando")
            continue

        print(f"\n  [{key.upper()}] {m['name']} tx={hex(m['tx'])} rx={hex(m['rx'])}")
        conn = None
        lid_results = {}
        try:
            conn = get_conn(dll, m["tx"], m["rx"], timeout=1.5)
            session, tentativas = kwp_session(conn)
            if session is None:
                print(f"    sem sessao — pulando")
                resultados[key] = {"status": "sem_sessao", "tentativas": {hex(k): v for k, v in tentativas.items()}}
                continue

            print(f"    sessao={hex(session)} OK — varrendo {len(lids)} LIDs...")
            respondidos = 0
            for lid in lids:
                try:
                    resp = kwp_read_lid(conn, lid, timeout=1.2)
                    if resp:
                        lid_results[hex(lid)] = resp.hex()
                        print(f"    LID {hex(lid):6} = {resp.hex()}")
                        respondidos += 1
                    else:
                        lid_results[hex(lid)] = None
                except Exception as e:
                    lid_results[hex(lid)] = f"ERRO:{e}"

            print(f"    Total respondidos: {respondidos}/{len(lids)}")
            resultados[key] = {
                "status": "OK",
                "session": hex(session),
                "lids": lid_results,
            }

        except Exception as e:
            print(f"    ERRO geral: {e}")
            resultados[key] = {"status": "erro", "detail": str(e)}
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    out = log_path("multi_lid_sweep")
    out.write_text(json.dumps(resultados, indent=2), encoding="utf-8")
    print(f"\n  Salvo: {out}")
    return resultados


def can_id_scan(dll, tx_start=0x700, tx_end=0x7FF):
    """Varre CAN IDs tentando sessao KWP (10 C0) e UDS (10 01).

    Cobre faixa 0x600-0x7FF para achar ABS/Airbag/HVAC.
    Testa RX = TX+0x08, TX+0x10 e TX+0x20 para cada TX.
    Apenas leitura — nunca escreve, nunca SecurityAccess.

    Resultado salvo em logs/can_id_scan_<ts>.json
    """
    sessions_to_try = [
        (0xC0, "KWP_C0"),
        (0x01, "UDS_01"),
    ]
    rx_offsets = (0x08, 0x10, 0x20)

    print_header("CAN ID SCAN AMPLIADO")
    print(f"  Faixa TX: {hex(tx_start)} a {hex(tx_end)}")
    print(f"  Sessoes: KWP 0xC0 + UDS 0x01")
    print(f"  Offsets RX: +0x08, +0x10, +0x20")
    total_ids = tx_end - tx_start + 1
    total_tentativas = total_ids * len(rx_offsets) * len(sessions_to_try)
    print(f"  Total tentativas: {total_tentativas}")
    total_pares = total_ids * len(rx_offsets)
    print(f"  Tempo estimado: ~{total_pares * 0.6 / 60:.0f} min\n")

    encontrados = []

    for i, tx in enumerate(range(tx_start, tx_end + 1)):
        if i % 16 == 0:
            print(f"  [{i}/{total_ids}] tx={hex(tx)}...", end="\r")

        for rx_offset in rx_offsets:
            rx = tx + rx_offset
            if rx > 0x7FF:
                continue
            # Abre UMA conexao por par TX/RX, tenta as sessoes em sequencia
            conn = None
            try:
                conn = get_conn(dll, tx, rx, timeout=0.5)
                for sess_byte, sess_name in sessions_to_try:
                    try:
                        resp = send_recv(conn, bytes([0x10, sess_byte]), timeout=0.5)
                        if resp and len(resp) >= 2 and resp[0] in (0x50, 0x7F):
                            status = "ACEITO" if resp[0] == 0x50 else f"NEG_{resp[2]:02X}"
                            print(f"\n  *** tx={hex(tx)} rx={hex(rx)} {sess_name} -> {status} resp={resp.hex()}")
                            encontrados.append({
                                "tx": hex(tx), "rx": hex(rx),
                                "session": hex(sess_byte), "protocol": sess_name,
                                "status": status, "resp": resp.hex()
                            })
                    except Exception:
                        pass
                time.sleep(0.05)
            except Exception:
                pass
            finally:
                if conn:
                    try: conn.close()
                    except Exception: pass

    print(f"\n  Scan concluido. Encontrados: {len(encontrados)}")
    resultado = {
        "faixa": f"{hex(tx_start)}-{hex(tx_end)}",
        "encontrados": encontrados
    }
    out = log_path("can_id_scan")
    out.write_text(json.dumps(resultado, indent=2), encoding="utf-8")
    print(f"  Salvo: {out}")
    return resultado

def enum_modules(dll):
    print_header("ENUMERAÇÃO DE MÓDULOS")
    resultado = {}
    for key, m in MODULES.items():
        try:
            conn = get_conn(dll, m["tx"], m["rx"], timeout=1.0)
            resp = send_recv(conn, bytes([0x10, 0x81]), timeout=1.0)
            conn.close()
            if resp:
                resultado[key] = {"status": "PRESENTE", "resp_hex": resp.hex()}
                print(f"  OK {key:8} tx={hex(m['tx'])} rx={hex(m['rx'])}  {m['name']}")
            else:
                resultado[key] = {"status": "SEM_RESPOSTA"}
                print(f"  -- {key:8} tx={hex(m['tx'])} rx={hex(m['rx'])}  sem resposta")
        except Exception as e:
            resultado[key] = {"status": "ERRO", "detail": str(e)}
            print(f"  ERR {key:8} ERRO: {e}")
    return resultado

def run_all(dll):
    out_dir = Path("logs"); out_dir.mkdir(exist_ok=True)
    session_ts = ts()
    print_header(f"SESSÃO COMPLETA NO CARRO — {session_ts}")
    print(f"  Nissan Sentra B16 2010 / JF011E CVT\n  DLL: {dll}\n")
    resultados = {}
    print_header("PASSO 1/6: Enumeração de módulos")
    resultados["enum"] = enum_modules(dll)
    print_header("PASSO 2/6: ECM via KWP (PRIORIDADE MAXIMA — nunca feito)")
    resultados["ecm"] = probe_module_full(dll, "ecm")
    print_header("PASSO 3/6: TCM — snapshot completo + sweep de LIDs desconhecidos")
    resultados["tcm"] = snapshot_tcm_all(dll, label="sessao_"+session_ts).name
    print_header("PASSO 4/6: BCM, IPDM, EPS, METER")
    for key in ["bcm", "ipdm", "eps", "meter"]:
        resultados[key] = probe_module_full(dll, key)
    print_header("PASSO 5/6: ABS, AIRBAG, HVAC (tentativa)")
    for key in ["abs", "airbag", "hvac"]:
        resultados[key] = probe_module_full(dll, key)
    print_header("PASSO 6/6: Polling correlacionado TCM + OBD")
    print("  Duracao: 5 minutos. Dirija normalmente — varie velocidade.")
    input("  Pressione ENTER quando estiver pronto para o polling...")
    resultados["correlated"] = correlated_poll(dll, duration_s=300.0, label=session_ts).name
    out = out_dir / f"session_summary_{session_ts}.json"
    out.write_text(json.dumps(resultados, indent=2, default=str), encoding="utf-8")
    print_header("SESSÃO CONCLUÍDA")
    print(f"  Resumo: {out}")
    print("  Próximo passo: copie a pasta logs/ e analise offline com o Claude.")

def main():
    parser = argparse.ArgumentParser(description="Sessão completa — Sentra B16 2010")
    parser.add_argument("comando",
                        choices=["all","enum","ecm","bcm","ipdm","eps","meter","tcm","correlated","field","ecm_sweep","ecm_sweep_full","reverse","module_probe","lid_sweep","can_scan","unk71e","abs","airbag","hvac"])
    parser.add_argument("--dll", default=DEFAULT_DLL)
    parser.add_argument("--duration", type=float, default=300.0)
    parser.add_argument("--label", default="")
    args = parser.parse_args()
    label = args.label or ts()
    if args.comando == "all": run_all(args.dll)
    elif args.comando == "enum": enum_modules(args.dll)
    elif args.comando == "tcm": snapshot_tcm_all(args.dll, label=label)
    elif args.comando == "correlated": correlated_poll(args.dll, duration_s=args.duration, label=label)
    elif args.comando == "field": guided_field_tests(args.dll)
    elif args.comando in MODULES: probe_module_full(args.dll, args.comando)
    elif args.comando == "ecm_sweep": ecm_lid_sweep(args.dll)
    elif args.comando == "ecm_sweep_full":
        # Só 0x21 sob sessão C0, sem SecurityAccess: procura o pulso de injeção (e o que mais houver).
        ecm_lid_sweep(args.dll, lids=list(range(0x00, 0x100)))
    elif args.comando == "reverse":   reverse_state_capture(args.dll)
    elif args.comando == "module_probe": module_quick_probe(args.dll)
    elif args.comando == "lid_sweep": multi_module_lid_sweep(args.dll)
    elif args.comando == "can_scan": can_id_scan(args.dll)
    else: parser.print_help()

if __name__ == "__main__":
    main()
