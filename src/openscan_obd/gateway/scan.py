"""Scan sob demanda (SDD 5.6): só leitura, tudo cru + decodificado, sem inventar.

Etapas: presença dos módulos (catálogo Nissan, NÃO é descoberta universal), ECM por
OBD, TCM e identificação dos demais. O estado de DTC do CVT fica sempre "nao_validado"
enquanto a leitura de DTC do TCM não for validada no carro (SDD 5.5): um scan nunca
diz que o câmbio está sem falhas.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

from openscan_obd.profiles import VehicleProfile, get_profile

LEGACY_PROFILE_ID = "nissan-sentra-b16-2010"      # padrão da biblioteca; a CLI usa generic-obd2
from openscan_obd.gateway.poller import OBD_FAST_PIDS, OBD_SLOW_PIDS, ECM_RX, ECM_TX, read_obd_dtcs
from openscan_obd.gateway.readonly_guard import ReadOnlyViolation
from openscan_obd.gateway.kwp_dtc17 import decode_status_of_dtc
from openscan_obd.gateway.tcm_lid01 import decode_tcm_lid01
from openscan_obd.obd2 import PID_TABLE, decode_live_data, decode_supported_pids

SCHEMA = 1
CATALOG_NOTE = ("Catálogo de módulos Nissan do veículo de teste (Sentra B16 2010); "
                "não é descoberta universal de ECUs.")
PID_NAMES = {**OBD_FAST_PIDS, **OBD_SLOW_PIDS}
STEPS = ("modulos", "ecm", "tcm", "outros")


def probe(device, req: bytes, timeout_ms: int = 300) -> dict:
    """Uma requisição; nunca levanta (exceto violação da guarda de leitura)."""
    out: dict = {"request": req.hex()}
    try:
        resp = device.send_recv(req, timeout_ms=timeout_ms)
    except ReadOnlyViolation:
        raise
    except TimeoutError:
        return {**out, "status": "timeout"}
    except Exception as exc:  # noqa: BLE001 — um passo não derruba o scan
        return {**out, "status": "error", "error": f"{type(exc).__name__}: {exc}"}
    if not resp:
        return {**out, "status": "no_response"}
    out["response"] = bytes(resp).hex()
    if resp[0] == 0x7F:
        return {**out, "status": "nrc", "nrc": f"{resp[2]:02X}" if len(resp) > 2 else "??"}
    return {**out, "status": "ok"}


def _set(device, tx: int, rx: int) -> bool:
    fn = getattr(device, "set_ids", None)
    if fn is None:
        return False
    fn(tx, rx)
    return True


def _supported(device, mode: int) -> list[int]:
    """Segue a cadeia de bitmaps (00, 20, 40...) enquanto o próximo bloco é declarado."""
    found: list[int] = []
    pid = 0x00
    while pid <= 0xC0:
        r = probe(device, bytes([mode, pid]))
        if r["status"] != "ok":
            break
        try:
            block = decode_supported_pids(bytes.fromhex(r["response"]), mode)
        except ValueError:
            break
        found += block
        nxt = pid + 0x20
        if nxt not in block:
            break
        pid = nxt
    return sorted(p for p in found if p % 0x20 != 0)


def _scan_modules(device, restore, modules: dict) -> dict:
    mods: dict = {}
    for name, m in modules.items():
        entry = {"tx": f"0x{m['tx']:03X}", "rx": f"0x{m['rx']:03X}", "note": m["note"]}
        if m["tx"] != ECM_TX and not _set(device, m["tx"], m["rx"]):
            mods[name] = {**entry, "present": None, "status": "skipped"}
            continue
        if m["tx"] == ECM_TX:
            _set(device, m["tx"], m["rx"])
        r = probe(device, b"\x3e")
        used = "3e"
        if r["status"] not in ("ok", "nrc") and m["tx"] != ECM_TX:
            # Alguns módulos (EPS, painel, BCM) ignoram 3E fora de sessão mas respondem a 10 C0.
            r2 = probe(device, b"\x10\xc0")
            if r2["status"] in ("ok", "nrc"):
                r, used = r2, "10c0"
        # qualquer resposta (positiva ou NRC) prova que o módulo está no barramento
        mods[name] = {**entry, "present": r["status"] in ("ok", "nrc"), "status": r["status"],
                      "probe": used}
        if "response" in r:
            mods[name]["response"] = r["response"]
    restore()
    return mods


def _scan_ecm(device) -> dict:
    _set(device, ECM_TX, ECM_RX)
    ecm: dict = {}
    supported = _supported(device, 0x01)
    ecm["supported_pids"] = supported
    live: dict = {}
    for pid in supported:
        if pid not in PID_TABLE:
            continue
        r = probe(device, bytes([0x01, pid]))
        key = PID_NAMES.get(pid, f"pid_{pid:02x}")
        if r["status"] == "ok":
            try:
                _, value, unit, name = decode_live_data(bytes.fromhex(r["response"]))
                live[key] = {"value": value, "unit": unit, "name": name,
                             "raw": r["response"], "pid": f"{pid:02X}"}
                continue
            except ValueError as exc:
                r = {**r, "status": "error", "error": str(exc)}
        live[key] = {"value": None, "status": r["status"], "raw": r.get("response", ""),
                     "pid": f"{pid:02X}"}
    ecm["live"] = live
    ecm["dtcs"] = read_obd_dtcs(device)
    ecm["dtcs_permanent_0a"] = probe(device, b"\x0a")
    mode9 = _supported(device, 0x09)
    ecm["mode09_supported"] = mode9
    # A4: o VIN (09 02) não é pedido se o bitmap 09 00 não o declara
    ecm["vin"] = (probe(device, b"\x09\x02") if 0x02 in mode9
                  else {"status": "nao_suportado", "reason": "bitmap 09 00 não declara o PID 02"})
    ecm["cal_id"] = probe(device, b"\x09\x04") if 0x04 in mode9 else {"status": "nao_suportado"}
    ecm["cvn"] = probe(device, b"\x09\x06") if 0x06 in mode9 else {"status": "nao_suportado"}
    return ecm


def _scan_tcm(device, modules: dict) -> dict:
    tcm_mod = modules["tcm_cvt"]
    if not _set(device, tcm_mod["tx"], tcm_mod["rx"]):
        return {"status": "skipped", "reason": "adaptador sem troca de IDs (set_ids)"}
    tcm: dict = {"status": "ok"}
    tcm["session"] = probe(device, b"\x10\xc0")
    r = probe(device, b"\x21\x01")
    lid: dict = {"status": r["status"], "request": r["request"]}
    if r["status"] == "ok":
        resp = bytes.fromhex(r["response"])
        if resp[:2] == b"\x61\x01":
            payload = b"\x01" + resp[2:]                  # decoder espera o eco do LID em [0]
            lid["raw"] = payload.hex()
            try:
                lid["decoded"] = decode_tcm_lid01(payload)
            except ValueError as exc:
                lid["status"] = "decode_error"
                lid["error"] = str(exc)
        else:
            lid["status"] = "unexpected"
            lid["raw"] = r["response"]
    else:
        for k in ("response", "nrc", "error"):
            if k in r:
                lid[k] = r[k]
    tcm["lid01"] = lid
    tcm["ident"] = {sub: probe(device, bytes([0x1A, int(sub, 16)])) for sub in ("80", "82", "83")}
    # H1 (SDD 5.5): tentativa por OBD no TCM. O resultado é só registrado cru.
    tcm["dtc"] = {
        "status": "nao_validado",
        "reason": "leitura de DTC do TCM ainda não validada no carro (KWP 18 recusado; OBD 03/07 "
                  "no TCM em teste). Não interpretar resposta vazia como 'sem falhas'.",
        "attempts": {f"{m:02X}": probe(device, bytes([m])) for m in (0x03, 0x07, 0x0A)},
        "codes": [],
    }
    # Hipótese (2026-11-16): KWP 17 FF 00 em sessão C0 devolve DTCs no TCM. Não confirmado
    # contra outra ferramenta; byte de status desconhecido; lista vazia nunca vira "sem falhas".
    k = probe(device, b"\x17\xff\x00")
    tcm["dtc"]["kwp_17"] = {key: k[key] for key in ("request", "status", "response", "nrc", "error") if key in k}
    if k["status"] == "ok":
        try:
            dec = decode_status_of_dtc(bytes.fromhex(k["response"]))
        except ValueError as exc:
            tcm["dtc"]["kwp_17"]["decode_error"] = str(exc)
        else:
            tcm["dtc"]["kwp_17"]["decoded"] = dec
            if dec["codes"]:
                tcm["dtc"]["status"] = "hipotese_nao_validada"
                tcm["dtc"]["codes"] = dec["codes"]
                tcm["dtc"]["reason"] = ("hipótese: códigos lidos por KWP 17 FF 00, ainda não "
                                        "confirmados em outra ferramenta; byte de status sem "
                                        "significado conhecido.")
    return tcm


def _scan_others(device, modules: dict, catalog: dict) -> dict:
    out: dict = {}
    for name, info in modules.items():
        if name in ("engine", "tcm_cvt") or not info.get("present"):
            continue
        m = catalog[name]
        if _set(device, m["tx"], m["rx"]):
            out[name] = {"ident_1a80": probe(device, b"\x1a\x80")}
    return out


def run_scan(device, progress: Callable[[str], None] | None = None,
             profile: VehicleProfile | None = None) -> dict:
    """Roda o scan completo. Sempre devolve os IDs do canal ao ECM no final.

    profile=None mantém o comportamento original (Sentra B16); a CLI e o dashboard passam o perfil.
    """
    profile = profile or get_profile(LEGACY_PROFILE_ID)
    def tick(step: str) -> None:
        if progress:
            progress(step)

    def restore() -> None:
        _set(device, ECM_TX, ECM_RX)

    result: dict = {"schema": SCHEMA, "ts": time.time(),
                    "data_source": getattr(device, "data_source", "unknown"),
                    "catalog_note": CATALOG_NOTE, "profile": profile.id}

    def step(name: str, fn):
        tick(name)
        try:
            return fn()
        except ReadOnlyViolation:
            raise
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        result["modules"] = step("modulos", lambda: _scan_modules(device, restore, profile.modules))
        result["ecm"] = step("ecm", lambda: _scan_ecm(device))
        if profile.has_tcm_lid01:
            result["tcm"] = step("tcm", lambda: _scan_tcm(device, profile.modules))
        else:
            result["tcm"] = {"status": "nao_aplicavel",
                             "reason": f"o perfil {profile.id} não tem leitura de câmbio"}
        result["others"] = step("outros", lambda: _scan_others(device, result["modules"], profile.modules))
    finally:
        restore()

    present = [n for n, m in result["modules"].items() if isinstance(m, dict) and m.get("present")]
    dtcs = result["ecm"].get("dtcs", {}) if isinstance(result["ecm"], dict) else {}
    result["summary"] = {
        "modules_present": present,
        "ecm_pids_supported": len(result["ecm"].get("supported_pids", [])),
        "dtc_ecm": {"stored": dtcs.get("stored"), "pending": dtcs.get("pending")},
        "dtc_cvt": ("nao_aplicavel" if result["tcm"].get("status") == "nao_aplicavel"
                    else (result["tcm"].get("dtc") or {}).get("status", "nao_validado")),
        "dtc_cvt_codes": [c["code"] for c in (result["tcm"].get("dtc") or {}).get("codes", [])],
        "vin": result["ecm"].get("vin", {}).get("status"),
    }
    return result


def save_scan(result: dict, logs_dir: Path, stamp: str | None = None,
              prefix: str = "scan") -> Path:
    """Grava logs/<prefix>_<stamp>.json sem sobrescrever (sufixo _2, _3... se já existir)."""
    stamp = stamp or time.strftime("%Y%m%d_%H%M%S", time.localtime(result.get("ts", time.time())))
    logs_dir = Path(logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        path = logs_dir / (f"{prefix}_{stamp}.json" if n == 1 else f"{prefix}_{stamp}_{n}.json")
        try:
            with path.open("x", encoding="utf-8") as fh:
                json.dump(result, fh, ensure_ascii=False, indent=2)
            return path
        except FileExistsError:
            n += 1
