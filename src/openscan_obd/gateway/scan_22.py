"""Varredura só de leitura do serviço 0x22 (ReadDataByIdentifier) num módulo.

Motivo: um aparelho de terceiros lê eixos A/B/saída do TCM com IDs de 2 bytes (1EBC, 1EC0, 1EC1) e o
nosso LID 01 não decodifica isso. A varredura de outubro só cobriu F180-F1AF e sem sessão.
Só envia `10 C0` (opcional) e `22 <DID>`; passa pela ReadOnlyDevice com 0x22 liberado
explicitamente. Guarda dados crus; nada é interpretado.
"""
from __future__ import annotations

import time
from typing import Callable

from openscan_obd.gateway.scan import probe

SCHEMA = 1
EARLY_STOP_AFTER = 16            # DIDs seguidos só com 0x11 => serviço não existe
BORING_NRCS = {"11", "31"}       # 11 serviço não suportado; 31 DID fora de faixa (só contados)


def _set(device, tx: int, rx: int) -> None:
    fn = getattr(device, "set_ids", None)
    if fn is not None:
        fn(tx, rx)


def run_scan_22(device, tx: int, rx: int, did_range: tuple[int, int] = (0x1E00, 0x1EFF),
                use_session: bool = True, timeout_ms: int = 200,
                progress: Callable[[int, int], None] | None = None,
                on_update: Callable[[dict], None] | None = None) -> dict:
    first, last = did_range
    found: list[dict] = []
    nrc_counts: dict[str, int] = {}
    nrc_dids: dict[str, list[str]] = {}
    state = {"tested": 0, "interrupted": False, "verdict": "completo", "session_c0": False}
    only_11 = 0
    result: dict = {"schema": SCHEMA, "ts": time.time(), "tx": f"0x{tx:03X}", "rx": f"0x{rx:03X}",
                    "range": [f"0x{first:04X}", f"0x{last:04X}"],
                    "note": "Respostas cruas; nada interpretado nem validado no veículo."}

    def snapshot() -> None:
        result["found"] = found
        result["nrc_counts"] = nrc_counts
        result["nrc_dids"] = nrc_dids
        result["summary"] = {"tested": state["tested"], "found": len(found),
                             "interrupted": state["interrupted"], "verdict": state["verdict"],
                             "session_c0": state["session_c0"]}
        if on_update:
            on_update(result)

    def read(did: int) -> dict:
        return probe(device, b"\x22" + did.to_bytes(2, "big"), timeout_ms=timeout_ms)

    try:
        _set(device, tx, rx)
        if use_session:
            s = probe(device, b"\x10\xc0", timeout_ms=300)
            result["session"] = s
            state["session_c0"] = s["status"] == "ok"
        for did in range(first, last + 1):
            if progress:
                progress(did, last - first + 1)
            r = read(did)
            state["tested"] += 1
            if r["status"] == "ok":
                found.append({"did": f"0x{did:04X}", "data": r["response"][6:], "raw": r["response"]})
                only_11 = 0
            elif r["status"] == "nrc":
                code = r["nrc"]
                nrc_counts[code] = nrc_counts.get(code, 0) + 1
                if code not in BORING_NRCS:
                    nrc_dids.setdefault(code, []).append(f"0x{did:04X}")
                only_11 = only_11 + 1 if code == "11" else 0
            else:
                only_11 = 0
            if only_11 >= EARLY_STOP_AFTER and state["tested"] == only_11:
                state["verdict"] = "servico_22_nao_suportado"
                break
            snapshot()
    except KeyboardInterrupt:
        state["interrupted"] = True
    finally:
        try:
            _set(device, 0x7E0, 0x7E8)
        except Exception:  # noqa: BLE001
            pass
    snapshot()
    return result
