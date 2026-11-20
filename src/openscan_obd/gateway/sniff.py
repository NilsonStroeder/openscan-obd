"""Escuta passiva do barramento CAN: grava TODO quadro que passa, sem enviar nada.

Abre o canal em CAN cru (protocolo 5) com filtro "passa tudo". Não há PassThruWriteMsgs aqui: o carro
só é ouvido. No GD101 esse canal não convive com o ISO15765 na mesma execução (reabrir falha), então a
escuta é uma captura própria. Os quadros ficam crus; a decodificação (rodas, pedais, painel) é feita
depois, em análise offline.
"""
from __future__ import annotations

import time
from ctypes import POINTER, byref, c_char, c_ulong
from typing import Callable

from openscan_obd.gateway.j2534 import (
    ERR_BUFFER_EMPTY, ERR_TIMEOUT, STATUS_NOERROR, J2534Error, PassThruMsg, _bind_prototypes,
    load_j2534_dll,
)

PROTOCOL_CAN = 5
PASS_FILTER = 0x01
NOTE = "Quadros CAN crus, apenas escuta; nada foi enviado ao carro."


class CanSniffer:
    data_source = "j2534-can-passivo"

    def __init__(self, dll_path: str, baudrate: int = 500_000, loader=load_j2534_dll) -> None:
        self.dll_path, self.baudrate, self._loader = dll_path, baudrate, loader
        self._lib = None
        self._dev, self._ch, self._flt = c_ulong(0), c_ulong(0), c_ulong(0)

    def open(self) -> None:
        self._lib = self._loader(self.dll_path)
        self._ok(self._lib.PassThruOpen(None, byref(self._dev)), "PassThruOpen")
        self._ok(self._lib.PassThruConnect(self._dev, PROTOCOL_CAN, 0, self.baudrate, byref(self._ch)),
                 "PassThruConnect(CAN)")
        mask, pattern = PassThruMsg(), PassThruMsg()
        for m in (mask, pattern):
            m.ProtocolID = PROTOCOL_CAN
            m.DataSize = 4                      # máscara 0 = passa qualquer ID
        self._ok(self._lib.PassThruStartMsgFilter(self._ch, PASS_FILTER, byref(mask), byref(pattern),
                                                  None, byref(self._flt)), "PassThruStartMsgFilter")

    def read(self, timeout_ms: int = 20) -> tuple[int, bytes, int] | None:
        msg = PassThruMsg()
        count = c_ulong(1)
        code = self._lib.PassThruReadMsgs(self._ch, byref(msg), byref(count), timeout_ms)
        if code in (ERR_BUFFER_EMPTY, ERR_TIMEOUT):
            return None
        self._ok(code, "PassThruReadMsgs")
        size = int(msg.DataSize)
        if size < 4:
            return None
        return int.from_bytes(bytes(msg.Data[0:4]), "big"), bytes(msg.Data[4:size]), int(msg.Timestamp)

    def close(self) -> None:
        if self._lib is None:
            return
        if self._ch.value:
            self._lib.PassThruDisconnect(self._ch)
            self._ch = c_ulong(0)
        if self._dev.value:
            self._lib.PassThruClose(self._dev)
            self._dev = c_ulong(0)

    def _ok(self, code: int, op: str) -> None:
        if code != STATUS_NOERROR:
            raise J2534Error(code, f"{op}: erro 0x{code:02X}")

    def __enter__(self) -> "CanSniffer":
        self.open()
        return self

    def __exit__(self, *a) -> None:
        self.close()


def run_sniff(sniffer, duration_s: float, write: Callable[[dict], None], *, meta: dict | None = None,
              clock: Callable[[], float] = time.monotonic, wall: Callable[[], float] = time.time) -> dict:
    ids: dict[str, dict] = {}
    seen: dict[str, set] = {}
    total = 0
    interrupted = False
    write({"event": "sniff_started", "t": round(wall(), 3), "meta": meta or {}, "note": NOTE})
    start = clock()
    try:
        while clock() - start < duration_s:
            fr = sniffer.read(20)
            if fr is None:
                continue
            can_id, data, ts = fr
            key, hexdata = f"{can_id:03X}", data.hex()
            write({"t": round(wall(), 4), "ts_us": ts, "id": key, "data": hexdata})
            total += 1
            info = ids.setdefault(key, {"count": 0, "distinct": 0})
            info["count"] += 1
            s = seen.setdefault(key, set())
            if len(s) < 4096 and hexdata not in s:
                s.add(hexdata)
                info["distinct"] = len(s)
    except KeyboardInterrupt:
        interrupted = True
    summary = {"frames": total, "ids": ids, "interrupted": interrupted,
               "elapsed_s": round(clock() - start, 1)}
    write({"event": "sniff_finished", "t": round(wall(), 3), "summary": summary})
    return summary
