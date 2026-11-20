"""Hipóteses de leitura de DTC do TCM (SDD 5.5, F4). Só leitura; resultado sempre cru.

H1  OBD 03/07/0A direto no TCM (0x7E1).
H2  OBD 03/07/0A por broadcast funcional 0x7DF (respostas em 0x7E8 e 0x7E9).
H3  KWP 13 e 17 (ISO 14230-3) sob sessão C0 no ECM e no TCM.
H5  SID A3 (fonte só da comunidade, semântica desconhecida). Condições: --allow-a3 e
    confirmação de carro parado em P, só depois de H1 a H3, um pedido por módulo, só ECM e
    TCM, parando na primeira resposta que não seja positiva nem NRC.

Nada aqui interpreta resposta: o bruto vai para o arquivo e vira hipótese não verificada.
"""
from __future__ import annotations

import time
from typing import Callable

from openscan_obd.gateway.scan import probe

SCHEMA = 1
ECM = (0x7E0, 0x7E8)
TCM = (0x7E1, 0x7E9)
FUNCTIONAL_TX = 0x7DF
OBD_DTC_MODES = (0x03, 0x07, 0x0A)
KWP_DTC_REQUESTS = (b"\x13", b"\x13\xff\x00", b"\x17", b"\x17\xff\x00")
A3 = b"\xa3"
A3_NOTE = ("Semântica do A3 desconhecida (fonte da comunidade): a resposta é registrada crua e "
           "é hipótese não verificada.")


def _set(device, ids: tuple[int, int]) -> None:
    fn = getattr(device, "set_ids", None)
    if fn is not None:
        fn(*ids)


def _obd_modes(device) -> dict:
    return {f"{m:02X}": probe(device, bytes([m])) for m in OBD_DTC_MODES}


def _classify_a3(r: dict) -> dict:
    """ok = resposta positiva (E3); nrc = 7F A3 xx; o resto é inesperado."""
    if r["status"] in ("ok", "nrc"):
        if r["status"] == "ok" and not r["response"].lower().startswith("e3"):
            return {**r, "status": "unexpected"}
        return r
    return {**r, "status": "unexpected" if r["status"] in ("no_response", "error") else r["status"]}


def run_probe(device, allow_a3: bool = False, confirm_parked: bool = False,
              progress: Callable[[str], None] | None = None) -> dict:
    def tick(name: str) -> None:
        if progress:
            progress(name)

    result: dict = {"schema": SCHEMA, "ts": time.time(),
                    "data_source": getattr(device, "data_source", "unknown"),
                    "note": "Resultados crus; nada foi interpretado nem validado no veículo."}
    try:
        tick("H1")
        _set(device, TCM)
        result["H1"] = {"tcm": _obd_modes(device)}

        tick("H2")
        result["H2"] = {}
        for mode in OBD_DTC_MODES:
            entry = {}
            for rx in (ECM[1], TCM[1]):
                _set(device, (FUNCTIONAL_TX, rx))
                entry[f"rx_{rx:03X}"] = probe(device, bytes([mode]))
            result["H2"][f"{mode:02X}"] = entry

        tick("H3")
        result["H3"] = {}
        for name, ids in (("ecm", ECM), ("tcm", TCM)):
            _set(device, ids)
            result["H3"][name] = {
                "session": probe(device, b"\x10\xc0"),
                "requests": {req.hex(): probe(device, req) for req in KWP_DTC_REQUESTS},
            }

        tick("H5")
        if not allow_a3:
            result["H5"] = {"status": "skipped", "reason": "A3 só roda com --allow-a3."}
        elif not confirm_parked:
            result["H5"] = {"status": "refused",
                            "reason": "A3 exige confirmação de que o carro está parado em P "
                                      "com o freio de mão puxado."}
        else:
            h5: dict = {"status": "done", "note": A3_NOTE}
            stop = False
            for name, ids in (("ecm", ECM), ("tcm", TCM)):
                if stop:
                    h5[name] = {"status": "stopped",
                                "reason": "parou na resposta inesperada anterior"}
                    continue
                _set(device, ids)
                probe(device, b"\x10\xc0")                    # sessão C0 aberta, como nos outros testes
                r = _classify_a3(probe(device, A3))
                h5[name] = r
                stop = r["status"] not in ("ok", "nrc")
            result["H5"] = h5
    finally:
        _set(device, ECM)
    return result
