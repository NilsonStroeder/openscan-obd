"""Coleta ampla, só de leitura: descobrir o que o carro responde e gravar tudo durante a condução.

Duas etapas, ambas por trás da ReadOnlyDevice (nada de escrita, limpeza ou rotinas):

* `run_discovery` (carro parado): PIDs OBD declarados e NÃO declarados (modo 01), modos 06 e 09, DTCs
  03/07/0A, e para cada módulo KWP do perfil: identificação (1A 80-9F) e varredura dos LIDs 00-FF.
  Módulo que não responde ao toque é pulado (não gasta a varredura inteira).
* `run_record` (carro andando): lê em ciclos todos os PIDs e LIDs que responderam e grava uma linha por
  leitura, com os bytes crus. Nada é interpretado; o objetivo é achar sinais que ainda não conhecemos.

O ritmo de cada módulo é configurável: o câmbio todo ciclo, os demais de vez em quando.
"""
from __future__ import annotations

import time
from typing import Callable

from openscan_obd.gateway.j2534 import J2534Error
from openscan_obd.gateway.scan import _supported, probe

SCHEMA = 1
NOTE = ("Respostas cruas; nada interpretado nem validado no veículo. Lista vazia de DTC não prova "
        "ausência de falhas.")
DEFAULT_EVERY = {"engine": 2, "tcm_cvt": 1}      # demais módulos: DEFAULT_SLOW_EVERY
DEFAULT_SLOW_EVERY = 5
KEEPALIVE_S = 1.5
ECM = (0x7E0, 0x7E8)


def _set(device, tx: int, rx: int) -> None:
    fn = getattr(device, "set_ids", None)
    if fn is not None:
        fn(tx, rx)


def _set_safe(device, tx: int, rx: int) -> bool:
    """Troca os IDs; se o filtro do GD101 falhar, refaz só o canal e tenta de novo uma vez."""
    try:
        _set(device, tx, rx)
        return True
    except (J2534Error, RuntimeError):
        reset = getattr(device, "reset_channel", None)
        if reset is None:
            return False
        try:
            reset()
            _set(device, tx, rx)
            return True
        except (J2534Error, RuntimeError):
            return False


RETRY_TIMEOUT_MS = 600


def read_lid(device, lid: int, timeout_ms: int, retry_timeout: bool = False) -> dict:
    """Lê `21 <lid>` e confere o eco (`61 <lid>`). Eco diferente = resposta atrasada de outro pedido.

    Na descoberta de 18/11 o câmbio devolveu dados de um LID sob o rótulo do seguinte. Por isso, com eco
    errado, repete uma vez com janela maior; se persistir, marca `mismatch` e guarda o eco observado
    (o dado não é descartado: alguns módulos podem usar outro número no eco).
    """
    r = probe(device, bytes([0x21, lid]), timeout_ms=timeout_ms)
    if r["status"] == "timeout" and retry_timeout:
        r = probe(device, bytes([0x21, lid]), timeout_ms=max(timeout_ms, RETRY_TIMEOUT_MS))
    if r["status"] != "ok":
        return r
    def echo(resp: dict) -> str:
        raw = bytes.fromhex(resp["response"])
        return f"{raw[1]:02X}" if len(raw) > 1 and raw[0] == 0x61 else ""
    r["echo"] = echo(r)
    if r["echo"] == f"{lid:02X}" or not r["echo"]:
        return r
    stale = r["response"]
    r2 = probe(device, bytes([0x21, lid]), timeout_ms=max(timeout_ms, RETRY_TIMEOUT_MS))
    if r2["status"] == "ok":
        r2["echo"] = echo(r2)
        if r2["echo"] == f"{lid:02X}":
            r2["stale"] = stale
            return r2
        r2["mismatch"] = True
        return r2
    r["mismatch"] = True
    return r


def parse_did_ranges(text: str) -> list[tuple[int, int]]:
    """"F100-F1FF,1E00" -> [(0xF100, 0xF1FF), (0x1E00, 0x1E00)]; "todos" = 0000-FFFF."""
    if text.strip().lower() in ("todos", "all"):
        return [(0, 0xFFFF)]
    out = []
    for part in text.split(","):
        a, _, b = part.strip().partition("-")
        lo, hi = int(a, 16), int(b or a, 16)
        if not 0 <= lo <= hi <= 0xFFFF:
            raise ValueError(f"faixa inválida: {part}")
        out.append((lo, hi))
    return out


def scan_dids(device, ranges, timeout_ms: int, progress=None, out: dict | None = None) -> dict:
    """Serviço 0x22 num módulo: um pedido de teste; só varre se o módulo aceita o serviço."""
    out = {} if out is None else out
    out.update({"status": "testando", "dids": {}, "nrc_dids": {}})
    t = probe(device, bytes([0x22, 0xF1, 0x90]), timeout_ms=timeout_ms)
    if t["status"] in ("timeout", "error", "no_response") or (
            t["status"] == "nrc" and t.get("nrc") == "11"):
        out.update({"status": "nao_suportado", "teste": t["status"]})
        return out
    out["status"] = "varrendo"
    total = sum(hi - lo + 1 for lo, hi in ranges)
    done = 0
    for lo, hi in ranges:
        for did in range(lo, hi + 1):
            r = probe(device, bytes([0x22, did >> 8, did & 0xFF]), timeout_ms=timeout_ms)
            if r["status"] == "ok":
                out["dids"][f"{did:04X}"] = r["response"]
            elif r["status"] == "nrc" and r.get("nrc") not in ("31", "12", "11"):
                out["nrc_dids"][f"{did:04X}"] = r["nrc"]       # existe mas recusou
            done += 1
            if progress and done % 1024 == 0:
                progress(done, total)
    out["status"] = "suportado"
    return out


def _discover_obd(device, pid_timeout_ms: int) -> dict:
    obd: dict = {}
    declared = _supported(device, 0x01)
    obd["declared_pids"] = [f"{p:02X}" for p in declared]
    declared_raw: dict[str, str] = {}
    for pid in declared:
        r = probe(device, bytes([0x01, pid]), timeout_ms=pid_timeout_ms)
        if r["status"] == "ok":
            declared_raw[f"{pid:02X}"] = r["response"]
    obd["declared_raw"] = declared_raw
    undeclared: dict[str, str] = {}
    for pid in range(0x01, 0x100):
        if pid in declared or pid % 0x20 == 0:
            continue
        r = probe(device, bytes([0x01, pid]), timeout_ms=pid_timeout_ms)
        if r["status"] == "ok" and r["response"].startswith(f"41{pid:02x}"):
            undeclared[f"{pid:02X}"] = r["response"]
    obd["undeclared_responders"] = undeclared
    for mode, key in ((0x09, "mode09"), (0x06, "mode06")):
        supported = _supported(device, mode)
        raws: dict[str, str] = {}
        for p in supported:
            r = probe(device, bytes([mode, p]), timeout_ms=300)
            if "response" in r:
                raws[f"{p:02X}"] = r["response"]
        obd[key] = {"supported": [f"{p:02X}" for p in supported], "raw": raws}
    obd["dtc_raw"] = {}
    for mode in (0x03, 0x07, 0x0A):
        r = probe(device, bytes([mode]), timeout_ms=300)
        obd["dtc_raw"][f"{mode:02X}"] = r.get("response", r["status"])
    return obd


def _discover_kwp_module(device, m: dict, lid_timeout_ms: int, progress, on_step) -> dict:
    entry: dict = {"tx": f"0x{m['tx']:03X}", "rx": f"0x{m['rx']:03X}", "status": "nao_respondeu",
                   "ident": {}, "lids": {}, "nrc_counts": {}, "timeouts": 0}
    if not _set_safe(device, m["tx"], m["rx"]):
        entry["status"] = "ids_nao_aplicados"
        return entry
    s = probe(device, b"\x10\xc0", timeout_ms=300)
    if s["status"] not in ("ok", "nrc"):
        s2 = probe(device, b"\x21\x01", timeout_ms=300)       # alguns módulos só falam o LID
        if s2["status"] not in ("ok", "nrc"):
            return entry
    entry["status"] = "respondeu"
    entry["session"] = s
    for opt in range(0x00, 0x100):
        r = probe(device, bytes([0x1A, opt]), timeout_ms=lid_timeout_ms)
        if r["status"] == "ok":
            entry["ident"][f"{opt:02X}"] = r["response"]
    for lid in range(0x00, 0x100):
        if lid and lid % 8 == 0:                             # mantém a sessão viva durante a varredura
            if probe(device, b"\x3e", timeout_ms=lid_timeout_ms)["status"] not in ("ok", "nrc"):
                probe(device, b"\x10\xc0", timeout_ms=300)
        r = read_lid(device, lid, lid_timeout_ms, retry_timeout=bool(entry["lids"]))
        if r.get("stale") and r["stale"][:2] == "61":   # atrasada de um LID que deu timeout: não perder
            raw = bytes.fromhex(r["stale"])
            if raw[0] == 0x61 and len(raw) > 1:
                entry["lids"].setdefault(f"{raw[1]:02X}", r["stale"])
                entry.setdefault("salvaged", []).append(f"{raw[1]:02X}")
        if r["status"] == "ok":
            entry["lids"][f"{lid:02X}"] = r["response"]
            if r.get("mismatch"):
                entry.setdefault("echo_mismatch", {})[f"{lid:02X}"] = r["echo"]
            elif r.get("stale"):
                entry.setdefault("stale_seen", {})[f"{lid:02X}"] = r["stale"]
        elif r["status"] == "nrc":
            entry["nrc_counts"][r["nrc"]] = entry["nrc_counts"].get(r["nrc"], 0) + 1
            if r["nrc"] != "12":                  # 12 = não existe; outro NRC = existe mas recusou agora
                entry.setdefault("nrc_lids", {})[f"{lid:02X}"] = r["nrc"]
        else:
            entry["timeouts"] += 1
        if progress:
            progress(lid + 1, 256)
        if on_step:
            on_step()
    return entry


def run_discovery(device, modules: dict, pid_timeout_ms: int = 80, lid_timeout_ms: int = 150,
                  did_ranges: list | None = None,
                  progress: Callable[[str, int, int], None] | None = None,
                  on_update: Callable[[dict], None] | None = None) -> dict:
    kwp_targets = {n: m for n, m in modules.items() if m.get("protocol") == "kwp"}
    if kwp_targets and "engine" in modules:
        kwp_targets = {"engine": modules["engine"], **kwp_targets}
    result: dict = {"schema": SCHEMA, "ts": time.time(),
                    "data_source": getattr(device, "data_source", "unknown"), "note": NOTE,
                    "obd": {}, "kwp": {}}

    def snap() -> None:
        if on_update:
            on_update(result)

    try:
        _set_safe(device, *ECM)
        result["obd"] = _discover_obd(device, pid_timeout_ms)
        snap()
        for name, m in kwp_targets.items():
            result["kwp"][name] = _discover_kwp_module(
                device, m, lid_timeout_ms,
                (lambda d, t, n=name: progress(n, d, t)) if progress else None, None)
            snap()
            if did_ranges and result["kwp"][name]["status"] == "respondeu":
                live: dict = {}
                result["kwp"][name]["svc22"] = live          # fica visível (e salvo) durante a varredura

                def prog(d, t, n=name):
                    if progress:
                        progress(n + " DID", d, t)
                    snap()
                scan_dids(device, did_ranges, lid_timeout_ms, prog, out=live)
                snap()
    except KeyboardInterrupt:
        result["interrupted"] = True
    finally:
        _set_safe(device, *ECM)
    snap()
    return result


def plan_from_discovery(disc: dict) -> dict:
    """Plano de gravação: PIDs OBD (declarados + não declarados que responderam) e LIDs que responderam."""
    obd = disc.get("obd", {})
    pids = {int(p, 16) for p in obd.get("declared_pids", [])}
    pids |= {int(p, 16) for p in obd.get("undeclared_responders", {})}
    kwp: dict = {}
    for name, e in disc.get("kwp", {}).items():
        dids = sorted({int(k, 16) for k in e.get("svc22", {}).get("dids", {})})
        if e.get("status") != "respondeu" or not (e.get("lids") or e.get("nrc_lids") or dids):
            continue
        kwp[name] = {"tx": int(e["tx"], 16), "rx": int(e["rx"], 16),
                     "lids": sorted({int(k, 16) for k in e["lids"]} | {int(k, 16) for k in e.get("nrc_lids", {})})}
        if dids:
            kwp[name]["dids"] = dids
    return {"obd_pids": sorted(pids), "kwp": kwp}


def plano_rapido(plan: dict, pids: str | None = None, so_obd: bool = False) -> dict:
    """Cópia do plano para gravar mais rápido: só alguns PIDs (hex separado por vírgula) e/ou sem módulos KWP.

    Sem os LIDs/DIDs, cada ciclo lê só o OBD e fica de dezenas de vezes mais curto: serve para puxadas de poucos segundos."""
    novo = {**plan, "obd_pids": list(plan.get("obd_pids", [])), "kwp": dict(plan.get("kwp", {}))}
    if pids:
        pedidos = {int(x, 16) for x in pids.split(",") if x.strip()}
        novo["obd_pids"] = [p for p in novo["obd_pids"] if p in pedidos]
    if so_obd:
        novo["kwp"] = {}
    return novo


def run_record(device, plan: dict, duration_s: float, write: Callable[[dict], None], *,
               meta: dict | None = None, every: dict | None = None,
               clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time,
               sleep: Callable[[float], None] = time.sleep,
               on_cycle: Callable[[int, float, int], None] | None = None) -> dict:
    cadence = {**DEFAULT_EVERY, **(every or {})}
    counts: dict[str, int] = {}
    stats = {"cycles": 0, "records": 0, "timeouts": 0, "interrupted": False, "skipped_visits": 0}
    last_touch: dict[str, float] = {}

    def emit(rec: dict) -> None:
        write(rec)
        stats["records"] += 1

    def read(src: str, req: bytes, timeout_ms: int, lid: int | None = None) -> dict:
        t0 = clock()
        r = read_lid(device, lid, timeout_ms) if lid is not None else probe(device, req, timeout_ms=timeout_ms)
        rec: dict = {"t": round(wall(), 3), "src": src}
        if r["status"] == "ok":
            rec["raw"] = r["response"]
            if r.get("mismatch"):
                rec["echo"] = r["echo"]
        elif r["status"] == "nrc":
            rec["nrc"] = r["nrc"]
        else:
            rec["status"] = r["status"]
            stats["timeouts"] += 1
        rec["ms"] = round((clock() - t0) * 1000, 1)
        counts[src] = counts.get(src, 0) + 1
        emit(rec)
        return r

    def touch(name: str) -> None:
        now = clock()
        if now - last_touch.get(name, -1e9) < KEEPALIVE_S:
            return
        r = probe(device, b"\x3e", timeout_ms=200)
        if r["status"] != "ok":
            probe(device, b"\x10\xc0", timeout_ms=300)
        last_touch[name] = now

    emit({"event": "coleta_started", "schema": SCHEMA, "t": round(wall(), 3), "meta": meta or {},
          "plan": {"obd_pids": [f"{p:02X}" for p in plan.get("obd_pids", [])],
                   "kwp": {n: [f"{x:02X}" for x in v["lids"]] for n, v in plan.get("kwp", {}).items()}},
          "note": NOTE})
    start = clock()
    try:
        for mode in (0x03, 0x07, 0x0A):
            _set_safe(device, *ECM)
            read(f"obd:modo{mode:02X}", bytes([mode]), 300)
        while clock() - start < duration_s:
            cycle = stats["cycles"]
            if _set_safe(device, *ECM):
                for pid in plan.get("obd_pids", []):
                    read(f"obd:{pid:02X}", bytes([0x01, pid]), 100)
            else:
                stats["skipped_visits"] += 1
            for name, mod in plan.get("kwp", {}).items():
                if cycle % cadence.get(name, DEFAULT_SLOW_EVERY) != 0:
                    continue
                if not _set_safe(device, mod["tx"], mod["rx"]):
                    stats["skipped_visits"] += 1
                    emit({"event": "modulo_pulado", "t": round(wall(), 3), "module": name})
                    continue
                touch(name)
                for lid in mod["lids"]:
                    read(f"kwp:{name}:{lid:02X}", bytes([0x21, lid]), 200, lid=lid)
                for did in mod.get("dids", []):
                    read(f"did:{name}:{did:04X}", bytes([0x22, did >> 8, did & 0xFF]), 200)
            stats["cycles"] += 1
            if on_cycle:
                on_cycle(stats["cycles"], clock() - start, stats["records"])
            sleep(0.01)
    except KeyboardInterrupt:
        stats["interrupted"] = True
    finally:
        _set_safe(device, *ECM)
    summary = {**stats, "elapsed_s": round(clock() - start, 1), "reads_by_source": counts}
    emit({"event": "coleta_finished", "t": round(wall(), 3), "summary": summary})
    return summary
