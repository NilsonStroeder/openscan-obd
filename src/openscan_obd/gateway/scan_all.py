"""Varredura longa de IDs CAN, só leitura (todas as "portas" 0x600-0x7FF).

Para cada ID de requisição tenta alguns IDs de resposta (+0x08, +0x10, +0x20). O toque é `10 C0`
(resposta positiva ou NRC prova que há módulo). Em cada módulo achado pede só leituras
(identificação, DTCs KWP, LID 01, OBD 01 00) e guarda tudo cru, sem interpretar.
Passa pela ReadOnlyDevice: nada de escrita, limpeza ou rotinas.
"""
from __future__ import annotations

import time
from typing import Callable

from openscan_obd.gateway.j2534 import J2534Error
from openscan_obd.gateway.scan import probe

SCHEMA = 1
RX_OFFSETS = (0x08, 0x10, 0x20)
FOLLOW_UP = (b"\x3e", b"\x1a\x80", b"\x17\xff\x00", b"\x13\xff\x00", b"\x21\x01", b"\x01\x00")
NOTE = ("Resposta crua; lista de DTC vazia não prova ausência de falhas. "
        "Nada foi interpretado nem validado no veículo.")


def _set(device, tx: int, rx: int) -> None:
    fn = getattr(device, "set_ids", None)
    if fn is not None:
        fn(tx, rx)


def _reopen(device) -> None:
    """Refaz só o canal J2534 (zera os filtros). Fechar/abrir o dispositivo derruba o GD101."""
    device.reset_channel()


def _set_with_reopen(device, tx: int, rx: int) -> None:
    try:
        _set(device, tx, rx)
    except J2534Error:
        _reopen(device)
        _set(device, tx, rx)


def run_scan_all(device, tx_range: tuple[int, int] = (0x600, 0x7FF),
                 rx_offsets: tuple[int, ...] = RX_OFFSETS, timeout_ms: int = 150,
                 progress: Callable[[int, int], None] | None = None,
                 on_update: Callable[[dict], None] | None = None) -> dict:
    first, last = tx_range
    total = last - first + 1
    found: list[dict] = []
    tested = 0
    interrupted = False
    aborted: str | None = None
    errors = 0
    result: dict = {"schema": SCHEMA, "ts": time.time(),
                    "data_source": getattr(device, "data_source", "unknown"),
                    "tx_range": [f"0x{first:03X}", f"0x{last:03X}"],
                    "rx_offsets": [f"+0x{o:02X}" for o in rx_offsets], "note": NOTE}
    def snapshot() -> None:
        result["found"] = found
        result["summary"] = {"tested_tx": tested, "found": len(found), "interrupted": interrupted,
                             "errors": errors, "aborted": aborted is not None, "abort_reason": aborted}
        if on_update:
            on_update(result)

    try:
        for tx in range(first, last + 1):
            if progress:
                progress(tx, total)
            tested += 1
            for off in rx_offsets:
                rx = tx + off
                if rx > 0x7FF:
                    continue
                _set_with_reopen(device, tx, rx)
                session = probe(device, b"\x10\xc0", timeout_ms=timeout_ms)
                if session["status"] not in ("ok", "nrc"):
                    continue
                entry = {"tx": f"0x{tx:03X}", "rx": f"0x{rx:03X}", "offset": f"+0x{off:02X}",
                         "session": session, "note": NOTE, "requests": {}}
                for req in FOLLOW_UP:
                    entry["requests"][req.hex()] = probe(device, req, timeout_ms=300)
                found.append(entry)
                break
            snapshot()
    except KeyboardInterrupt:
        interrupted = True
    except J2534Error as exc:        # adaptador sem conserto: guarda o que já achou
        aborted = str(exc)
        tested -= 1                  # o ID em curso não foi concluído
    finally:
        try:
            _set(device, 0x7E0, 0x7E8)
        except J2534Error:
            pass
    snapshot()
    return result
