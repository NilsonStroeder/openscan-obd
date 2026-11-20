"""FastAPI integration for the KWP gateway and live dashboard."""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from openscan_obd.gateway.capture import JsonlFrameCapture
from openscan_obd.gateway.elm327 import ELM327Error
from openscan_obd.gateway.j2534 import J2534Error
from openscan_obd.gateway.kwp_session import KWPSession, KWPSessionError
from openscan_obd.gateway.poller import KWPPoller
from openscan_obd.gateway.readonly_guard import ReadOnlyDevice
from openscan_obd.gateway.scan import run_scan, save_scan
from openscan_obd.profiles import DEFAULT_PROFILE_ID, get_profile

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
DEFAULT_DLL = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"
ECM_TX = 0x7E0
ECM_RX = 0x7E8


def _mode(app: FastAPI) -> str:
    if app.state.mock:
        return "mock"
    return "elm327" if app.state.elm_port else "j2534"


def _make_device(mock: bool, dll_path: str, elm_port: str | None = None):
    if mock:
        from openscan_obd.gateway.j2534_mock import J2534DeviceMock

        return J2534DeviceMock()
    if elm_port:
        from openscan_obd.gateway.elm327 import ELM327Device

        return ELM327Device(elm_port, txid=ECM_TX, rxid=ECM_RX)
    from openscan_obd.gateway.j2534 import J2534Device

    return J2534Device(dll_path, txid=ECM_TX, rxid=ECM_RX)


def _idle_scan() -> dict:
    return {"state": "idle", "step": None, "result": None, "file": None, "error": None,
            "started": None}


def _run_scan_job(app: FastAPI) -> None:
    """Roda o scan numa thread, com o poller pausado (canal único)."""
    def progress(step: str) -> None:
        app.state.scan["step"] = step

    try:
        with app.state.poller.exclusive():
            result = run_scan(app.state.device, progress=progress, profile=app.state.profile)
        path = save_scan(result, app.state.scan_dir)
        app.state.scan = {**app.state.scan, "state": "done", "step": None,
                          "result": result, "file": str(path)}
    except Exception as exc:  # noqa: BLE001 — o erro vai para a tela, não derruba a API
        logger.exception("Falha no scan")
        app.state.scan = {**app.state.scan, "state": "error", "step": None,
                          "error": f"{type(exc).__name__}: {exc}"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Tudo que chega ao adaptador passa pela guarda de somente leitura (SDD 5.4).
    device = ReadOnlyDevice(_make_device(app.state.mock, app.state.dll_path, app.state.elm_port))
    try:
        device.open()
    except Exception:
        device.close()
        raise
    session = KWPSession(device)
    session_error = None
    try:
        session.start()
    except (KWPSessionError, J2534Error, ELM327Error, TimeoutError) as exc:
        session_error = str(exc)

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict] = asyncio.Queue()
    condition = asyncio.Condition()
    app.state.session = session
    app.state.device = device
    app.state.session_error = session_error
    capture: JsonlFrameCapture | None = None
    if app.state.capture_path is not None:
        capture = JsonlFrameCapture(
            app.state.capture_path,
            {
                "mode": _mode(app),
                "vehicle": app.state.capture_metadata["vehicle"],
                "vehicle_profile": app.state.profile.id,
                "ecu": app.state.capture_metadata["ecu"],
                "tx": f"0x{ECM_TX:03X}",
                "rx": f"0x{ECM_RX:03X}",
                "protocol": "KWP",
                "adapter": app.state.capture_metadata["adapter"],
                "dll_path": None if app.state.mock or app.state.elm_port else app.state.dll_path,
                "elm_port": None if app.state.mock else app.state.elm_port,
                "validation_status": "not_validated",
            },
        )
        try:
            capture.open()
        except OSError:
            device.close()
            raise
    app.state.capture = capture
    app.state.capture_error = None
    app.state.latest_frame = None
    app.state.frame_seq = 0
    app.state.started_at = time.monotonic()
    app.state.frame_condition = condition

    poller = KWPPoller(session, queue, loop, tcm_enabled=app.state.profile.has_tcm_lid01)
    poller.start()
    app.state.poller = poller

    async def consume_frames() -> None:
        while True:
            frame = await queue.get()
            if app.state.capture is not None:
                try:
                    app.state.capture.write_frame(frame)
                except OSError as exc:
                    app.state.capture_error = f"{type(exc).__name__}: {exc}"
                    logger.exception("Falha ao gravar captura KWP; captura desativada")
                    try:
                        app.state.capture.close()
                    except OSError:
                        logger.exception("Falha ao fechar arquivo de captura KWP")
                    app.state.capture = None
            async with condition:
                app.state.latest_frame = frame
                app.state.frame_seq += 1
                condition.notify_all()

    consumer = asyncio.create_task(consume_frames(), name="kwp-frame-consumer")
    try:
        yield
    finally:
        poller.stop()
        consumer.cancel()
        try:
            await consumer
        except asyncio.CancelledError:
            pass
        try:
            if app.state.capture is not None:
                app.state.capture.close()
        finally:
            try:
                session.stop()
            finally:
                device.close()


def create_app(
    mock: bool | None = None,
    dll_path: str | None = None,
    capture_path: Path | None = None,
    capture_metadata: dict[str, str] | None = None,
    elm_port: str | None = None,
    scan_dir: Path | None = None,
    profile: str | None = None,
) -> FastAPI:
    profile_id = profile or os.environ.get("NISSAN_SCANNER_PROFILE") or DEFAULT_PROFILE_ID
    vehicle_profile = get_profile(profile_id)       # perfil desconhecido falha aqui, antes de subir
    if mock is None:
        mock = os.environ.get("NISSAN_SCANNER_MOCK", "1") != "0"
    app = FastAPI(
        title="NissanScan",
        description="API do gateway KWP. Mock por padrão; hardware requer configuração explícita.",
        version="0.2.0",
        lifespan=lifespan,
    )
    app.state.mock = mock
    app.state.profile = vehicle_profile
    app.state.elm_port = None if mock else elm_port
    app.state.dll_path = dll_path or os.environ.get("NISSAN_SCANNER_DLL", DEFAULT_DLL)
    app.state.capture_path = capture_path
    app.state.capture_metadata = capture_metadata or {
        "vehicle": "not_recorded",
        "ecu": "ECM configured; not discovered",
        "adapter": "not_recorded",
    }
    app.state.capture_error = None
    app.state.latest_frame = None
    app.state.session_error = None
    app.state.scan_dir = Path(
        scan_dir if scan_dir is not None else os.environ.get("NISSAN_SCANNER_SCAN_DIR", "logs")
    )
    app.state.scan = _idle_scan()
    app.state.scan_lock = threading.Lock()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    index_name = "index.html" if (STATIC_DIR / "index.html").exists() else "dashboard.html"

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / index_name)

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/api/status")
    async def get_status() -> dict:
        frame = app.state.latest_frame
        return {
            "mode": _mode(app),
            "data_source": getattr(app.state.device, "data_source", None)
            if hasattr(app.state, "device") else None,
            "hardware_connected": bool(
                not app.state.mock and frame and frame.get("conn")
            ),
            "session_active": bool(
                hasattr(app.state, "session") and app.state.session.active
            ),
            "session_error": (
                None if frame and frame.get("conn")
                else frame.get("error") if frame
                else app.state.session_error
            ),
            "capture_enabled": getattr(app.state, "capture", None) is not None,
            "capture_error": app.state.capture_error,
            "uptime_s": round(time.monotonic() - app.state.started_at, 1)
            if hasattr(app.state, "started_at") else 0.0,
            "vehicle_profile": app.state.profile.id,
            "tcm_supported": app.state.profile.has_tcm_lid01,
        }

    @app.get("/api/modules")
    async def get_modules() -> dict:
        return {
            "data_source": "configuration_only",
            "modules": [{
                "name": "ECM",
                "tx": f"0x{ECM_TX:03X}",
                "rx": f"0x{ECM_RX:03X}",
                "protocol": "kwp",
                "status": "configured_not_discovered",
            }],
        }

    @app.get("/api/params")
    async def get_params() -> dict:
        frame = app.state.latest_frame
        if frame is None:
            return {
                "data_source": "unavailable",
                "conn": False,
                "lid_available": False,
                "message": "Aguardando o primeiro ciclo de polling.",
            }
        return frame

    @app.get("/api/dtcs")
    async def get_dtcs() -> dict:
        result = app.state.scan.get("result")
        if not result:
            return {
                "performed": False,
                "dtcs": None,
                "message": (
                    "Nenhum scan executado. Use o botão Scan (POST /api/scan); a leitura é "
                    "somente leitura e a de DTC do CVT ainda não foi validada no veículo."
                ),
            }
        ecm = result.get("ecm", {}).get("dtcs", {})
        return {
            "performed": True,
            "scan_ts": result.get("ts"),
            "ecm": {"stored": ecm.get("stored"), "pending": ecm.get("pending"),
                    "raw": ecm.get("raw")},
            "cvt": result.get("tcm", {}).get("dtc", {"status": "nao_validado"}),
            "message": "Resultado do último scan. DTC do CVT: não validado (nunca 'sem falhas').",
        }

    @app.get("/api/scan")
    async def get_scan() -> dict:
        return dict(app.state.scan)

    @app.post("/api/scan", status_code=202)
    async def start_scan(request: Request) -> dict:
        # Bloqueia disparo por outra origem (página web aberta no mesmo navegador).
        origin = request.headers.get("origin")
        if origin is not None and urlparse(origin).netloc != request.headers.get("host"):
            raise HTTPException(status_code=403, detail="origem não permitida")
        with app.state.scan_lock:
            if app.state.scan["state"] == "running":
                raise HTTPException(status_code=409, detail="scan já em andamento")
            app.state.scan = {**_idle_scan(), "state": "running", "started": time.time()}
        threading.Thread(target=_run_scan_job, args=(app,), name="scan", daemon=True).start()
        return {"state": "running"}

    @app.websocket("/ws/live")
    async def live_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        condition: asyncio.Condition = app.state.frame_condition
        seen_seq = 0
        try:
            while True:
                try:
                    async with condition:
                        await asyncio.wait_for(
                            condition.wait_for(lambda: app.state.frame_seq > seen_seq),
                            timeout=5.0,
                        )
                        seen_seq = app.state.frame_seq
                        frame = app.state.latest_frame
                except TimeoutError:
                    await websocket.send_json({
                        "conn": False,
                        "data_source": "unavailable",
                        "message": "Nenhum frame recebido nos últimos 5 segundos.",
                    })
                    continue
                await websocket.send_json(frame)
        except WebSocketDisconnect:
            return

    return app


app = create_app()


def main(
    host: str = "127.0.0.1",
    port: int = 8000,
    mock: bool = True,
    dll_path: str | None = None,
    capture_path: Path | None = None,
    capture_metadata: dict[str, str] | None = None,
    elm_port: str | None = None,
    profile: str | None = None,
) -> None:
    import uvicorn

    uvicorn.run(
        create_app(
            mock=mock,
            dll_path=dll_path,
            capture_path=capture_path,
            capture_metadata=capture_metadata,
            elm_port=elm_port,
            profile=profile,
        ),
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
