"""Polling KWP em thread separada. Nunca chama a DLL a partir de uma corrotina."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import threading
import time
from contextlib import contextmanager

from openscan_obd.gateway import frame_v2
from openscan_obd.gateway.decoder import decode_ecm_lid01
from openscan_obd.gateway.kwp_reader import (
    STATUS_NEGATIVE,
    STATUS_POSITIVE,
    read_lid_detailed,
)
from openscan_obd.gateway.kwp_session import KWPSession, KWPSessionError
from openscan_obd.gateway.tcm_lid01 import decode_tcm_lid01
from openscan_obd.obd2 import decode_dtc_response, decode_live_data

ECM_TX = 0x7E0
ECM_RX = 0x7E8
TCM_TX = 0x7E1
TCM_RX = 0x7E9
LID_01 = 0x01

# PIDs de modo 01 lidos em paralelo ao LID KWP (chave plana no dict "obd").
# O ECM do B16 responde a modo 01 (ver logs/full_scan_20261115_184513.txt),
# enquanto o LID 0x01 dele tem só 4 bytes — curto demais para o decoder B17.
OBD_LIVE_PIDS: dict[int, str] = {0x05: "ect", 0x0C: "rpm", 0x0D: "vsp", 0x11: "tps"}

# Grupos do dashboard: rápidos a cada ciclo; lentos um por ciclo, em rodízio.
OBD_FAST_PIDS: dict[int, str] = {0x0C: "rpm", 0x0D: "vsp", 0x11: "tps", 0x04: "load"}
OBD_SLOW_PIDS: dict[int, str] = {
    0x05: "ect", 0x0F: "iat", 0x10: "maf", 0x42: "vbat", 0x06: "stft", 0x07: "ltft",
    0x0E: "timing", 0x14: "o2_b1s1", 0x15: "o2_b1s2", 0x43: "abs_load",
    # declarados pelo ECM real (bitmaps de 2026-11-15) e ainda não lidos ao vivo:
    0x1F: "runtime", 0x44: "lambda_cmd", 0x46: "ambient", 0x4C: "tps_cmd",
}


def read_obd_live(device, pids: dict[int, str] | None = None,
                  timeout_ms: int = 200) -> dict:
    """Lê PIDs OBD-II de modo 01 e devolve dict com valor decodificado + hex cru.

    Modo 01 não exige sessão KWP (10 C0). Falha de um PID não derruba os
    outros: resposta 7F vira {"nrc": ...}, timeout vira {"error": ...}.
    Estrutura: {"ok": bool, "raw": {"0C": "410c0b18", ...}, "pids": {...},
    "rpm": 710.0, ...} — as chaves planas (ect/rpm/vsp/tps) só aparecem
    quando o PID respondeu positivo.
    """
    pids = OBD_LIVE_PIDS if pids is None else pids
    out: dict = {"raw": {}, "pids": {}}
    for pid, key in pids.items():
        try:
            resp = device.send_recv(bytes([0x01, pid]), timeout_ms=timeout_ms)
        except Exception as exc:  # noqa: BLE001 — um PID não pode parar os outros
            out["pids"][key] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        out["raw"][f"{pid:02X}"] = resp.hex() if resp else ""
        if not resp:
            out["pids"][key] = {"error": "sem resposta"}
        elif resp[0] == 0x7F:
            out["pids"][key] = {"nrc": f"{resp[2]:02X}" if len(resp) > 2 else "??"}
        else:
            try:
                got, value, unit, name = decode_live_data(resp)
                if got != pid:       # resposta de outro PID (atrasada): nunca vira valor deste
                    out["pids"][key] = {
                        "error": f"resposta de outro PID (0x{got:02X}, esperado 0x{pid:02X})"}
                    continue
                out["pids"][key] = {"value": value, "unit": unit, "name": name}
                out[key] = value
            except ValueError as exc:
                out["pids"][key] = {"error": str(exc)}
    out["ok"] = any("value" in p for p in out["pids"].values())
    return out


def read_obd_dtcs(device, timeout_ms: int = 500) -> dict:
    """Lê DTCs por OBD-II modos 03 (armazenados) e 07 (pendentes) — só leitura.

    Nunca envia modo 04 (limpeza). Falha de um modo não derruba o outro.
    Estrutura: {"raw": {"03": "4300", ...}, "stored": [...], "pending": [...]}
    """
    out: dict = {"raw": {}}
    for mode, key in ((0x03, "stored"), (0x07, "pending")):
        try:
            resp = device.send_recv(bytes([mode]), timeout_ms=timeout_ms)
            out["raw"][f"{mode:02X}"] = resp.hex() if resp else ""
            if not resp:
                out[key] = {"error": "sem resposta"}
            elif resp[0] == 0x7F:
                out[key] = {"nrc": f"{resp[2]:02X}" if len(resp) > 2 else "??"}
            else:
                out[key] = decode_dtc_response(resp, mode)
        except Exception as exc:  # noqa: BLE001 — um modo não pode parar o outro
            out[key] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


class KWPPoller:
    def __init__(
        self,
        session: KWPSession,
        queue: asyncio.Queue,
        loop: asyncio.AbstractEventLoop,
        interval_s: float = 0.1,
        keepalive_s: float = 2.0,
        module_tx: int = ECM_TX,
        tcm_every: int = 1,
        tcm_enabled: bool = True,
    ) -> None:
        self.session = session
        self.queue = queue
        self.loop = loop
        self.interval_s = interval_s
        self.keepalive_s = keepalive_s
        self.module_tx = module_tx
        self.tcm_every = max(1, tcm_every)
        self.tcm_enabled = tcm_enabled
        self.schedule = frame_v2.ObdSchedule(OBD_FAST_PIDS, OBD_SLOW_PIDS)
        self._values: dict = {}
        self._cvt: dict = {}
        self._cycle = 0
        self._ecm_ok: float | None = None
        self._tcm_ok: float | None = None
        self._tcm_error: str | None = None
        self._tcm_raw: str | None = None      # hex da resposta 61 01 ... do ciclo atual
        self._tcm_session = KWPSession(session.device)
        self._tcm_last_ka = 0.0
        # latências medidas (F2): vão no frame e portanto na captura
        self._obd_ms: float | None = None
        self._tcm_ms: float | None = None
        self._obd_t: float | None = None
        self._tcm_t: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._io_lock = threading.Lock()      # dono do canal: ciclo do poller OU scan

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="kwp-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def _publish(self, params: dict) -> None:
        asyncio.run_coroutine_threadsafe(self.queue.put(params), self.loop)

    @contextmanager
    def exclusive(self):
        """Pausa a leitura ao vivo e dá o canal a quem chamou (ex.: scan). O poller
        publica frames `paused` enquanto isso e retoma ao sair do bloco."""
        with self._io_lock:
            try:
                yield
            finally:
                # o scan pode durar mais que o P3 das sessões KWP: reabrir no próximo ciclo
                self.session.stop()
                self._tcm_session.stop()

    def _paused_frame(self, data_source: str) -> dict:
        now_m = time.monotonic()
        frame = frame_v2.build_frame(
            ts=time.time(), conn=True, data_source=data_source, values=self._values,
            cvt=self._cvt, now=now_m,
            modules={"ecm": frame_v2.module_state(self._ecm_ok, now_m),
                     "tcm": frame_v2.module_state(self._tcm_ok, now_m)})
        frame["paused"] = True
        frame["message"] = "Scan em andamento: leitura ao vivo pausada."
        return frame

    def _read_obd(self) -> None:
        batch = self.schedule.next_batch()
        t0 = time.monotonic()
        res = read_obd_live(self.session.device, batch)
        now = time.monotonic()
        self._obd_ms = (now - t0) * 1000
        self._obd_t = now
        frame_v2.update_obd_cache(self._values, res, batch, now,
                                  slow_pids=set(self.schedule.slow))
        for pid, key in batch.items():
            self.schedule.record(pid, res["pids"].get(key, {}))
        if res["ok"]:
            self._ecm_ok = now

    def _read_tcm(self) -> None:
        """LID 0x01 do TCM: troca os IDs do canal, lê e SEMPRE volta para o ECM."""
        device = self.session.device
        set_ids = getattr(device, "set_ids", None)
        if set_ids is None:
            return                      # adaptador sem troca de IDs: TCM indisponível
        t0 = time.monotonic()
        self._tcm_raw = None
        try:
            set_ids(TCM_TX, TCM_RX)
            now = time.monotonic()
            if not self._tcm_session.active:
                self._tcm_session.start()
                self._tcm_last_ka = now
            elif now - self._tcm_last_ka >= self.keepalive_s:
                self._tcm_session.keep_alive()
                self._tcm_last_ka = now
            result = read_lid_detailed(self._tcm_session, LID_01)
            if result.status == STATUS_POSITIVE:
                self._tcm_raw = result.raw.hex()
                decoded = decode_tcm_lid01(b"\x01" + result.payload)
                frame_v2.update_tcm_cache(self._cvt, decoded, now)
                self._tcm_ok = now
                self._tcm_t = now
                self._tcm_error = None
            else:
                nrc = f" NRC 0x{result.nrc:02X}" if result.nrc is not None else ""
                self._tcm_error = f"LID 0x01 {result.status}{nrc}"
        except Exception as exc:  # noqa: BLE001 — falha do TCM não derruba o ECM
            self._tcm_error = f"{type(exc).__name__}: {exc}"
            self._tcm_session.stop()
        finally:
            try:
                set_ids(ECM_TX, ECM_RX)
            except Exception:  # noqa: BLE001
                pass
            self._tcm_ms = (time.monotonic() - t0) * 1000

    def _loop(self) -> None:
        last_ka = 0.0
        failures = 0
        retry_at = 0.0
        data_source = getattr(self.session.device, "data_source", "unknown")
        while not self._stop.is_set():
            now = time.monotonic()
            if now < retry_at:
                self._stop.wait(min(self.interval_s, retry_at - now))
                continue
            if not self._io_lock.acquire(blocking=False):
                self._publish(self._paused_frame(data_source))
                self._stop.wait(self.interval_s)
                continue
            try:
                cycle_t0 = time.monotonic()
                wall_time = time.time()
                params: dict = {
                    "ts": wall_time,
                    "conn": False,
                    "data_source": data_source,
                    "lid_available": False,
                    "raw_lid01": None,
                    "raw_tcm_lid01": None,
                }
                try:
                    if not self.session.active:
                        self.session.start()
                    if wall_time - last_ka >= self.keepalive_s:
                        self.session.keep_alive()
                        last_ka = wall_time
                    result = read_lid_detailed(self.session, LID_01)
                    params["lid_response"] = result.status
                    params["raw_lid_response"] = result.raw.hex()
                    if result.status == STATUS_NEGATIVE:
                        params["lid_nrc"] = f"{result.nrc:02x}"
                    if result.status == STATUS_POSITIVE:
                        raw = result.payload
                        params["lid_available"] = True
                        params["raw_lid01"] = raw.hex()
                        try:
                            params.update(decode_ecm_lid01(raw))
                        except ValueError as exc:
                            params["decode_error"] = str(exc)
                    self._read_obd()
                    self._tcm_raw = None
                    if self.tcm_enabled and self._cycle % self.tcm_every == 0:
                        self._read_tcm()
                    params["raw_tcm_lid01"] = self._tcm_raw
                    self._cycle += 1
                    params["conn"] = True
                    failures = 0
                    retry_at = 0.0
                except Exception as exc:  # noqa: BLE001 — o loop não pode morrer
                    params["conn"] = False
                    params["error"] = f"{type(exc).__name__}: {exc}"
                    self.session.stop()
                    failures += 1
                    retry_delay = min(5.0, 2.0 ** min(failures - 1, 3))
                    retry_at = time.monotonic() + retry_delay
                now_m = time.monotonic()
                skew = (None if self._tcm_t is None or self._obd_t is None
                        else round((self._tcm_t - self._obd_t) * 1000, 1))
                params["timing"] = {
                    "cycle_ms": round((now_m - cycle_t0) * 1000, 1),
                    "obd_ms": None if self._obd_ms is None else round(self._obd_ms, 1),
                    "tcm_ms": None if self._tcm_ms is None else round(self._tcm_ms, 1),
                    "tcm_obd_skew_ms": skew,
                }
                v2 = frame_v2.build_frame(
                    ts=wall_time, conn=params["conn"], data_source=data_source,
                    values=self._values, cvt=self._cvt, now=now_m,
                    modules={"ecm": frame_v2.module_state(self._ecm_ok, now_m, params.get("error")),
                             "tcm": frame_v2.module_state(self._tcm_ok, now_m, self._tcm_error)})
                verified = v2.pop("verified", None) and "profile" not in params
                params.update({k: v for k, v in v2.items() if k not in ("ts", "conn", "data_source")})
                if verified:
                    params["verified"] = True
            finally:
                self._io_lock.release()
            self._publish(params)
            self._stop.wait(self.interval_s)


async def _print_frames(queue: asyncio.Queue, duration_s: float | None) -> None:
    deadline = None if duration_s is None else time.monotonic() + duration_s
    while deadline is None or time.monotonic() < deadline:
        timeout = 1.0 if deadline is None else max(0.1, deadline - time.monotonic())
        try:
            params = await asyncio.wait_for(queue.get(), timeout=timeout)
        except TimeoutError:
            continue
        print(json.dumps(params, default=str), flush=True)


def run_terminal(mock: bool, duration_s: float | None, dll_path: str | None) -> None:
    if mock:
        from openscan_obd.gateway.j2534_mock import J2534DeviceMock

        device = J2534DeviceMock()
    else:
        if not dll_path:
            raise SystemExit("informe --dll para polling com hardware")
        from openscan_obd.gateway.j2534 import J2534Device

        device = J2534Device(dll_path)
    device.open()
    session = KWPSession(device)
    try:
        session.start()
    except KWPSessionError as exc:
        print(f"falha ao abrir sessão KWP: {exc}", file=sys.stderr)
        device.close()
        raise SystemExit(1) from exc

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        poller = KWPPoller(session, queue, loop)
        poller.start()
        try:
            await _print_frames(queue, duration_s)
        finally:
            poller.stop()

    try:
        asyncio.run(_main())
    finally:
        session.stop()
        device.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Polling KWP no terminal, sem FastAPI.")
    parser.add_argument("--mock", action="store_true", help="Usa J2534DeviceMock e fixture gravada.")
    parser.add_argument("--dll", default=None, help="Caminho da DLL J2534 (Python 32-bit).")
    parser.add_argument("--duration", type=float, default=None, help="Segundos; omitir para rodar até Ctrl+C.")
    args = parser.parse_args(argv)
    run_terminal(mock=args.mock, duration_s=args.duration, dll_path=args.dll)


if __name__ == "__main__":
    main()
