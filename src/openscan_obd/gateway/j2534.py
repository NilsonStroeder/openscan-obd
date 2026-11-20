"""Wrapper J2534 de baixo nível via ctypes.

Carrega a DLL, conecta ISO15765 e expõe send_recv(bytes) -> bytes.
Não abre sessão KWP: isso fica em kwp_session.py.

A DLL GODIAG_PT32.dll é 32-bit; este módulo precisa de Python 32-bit no Windows.
"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_char, c_ulong, c_void_p

STATUS_NOERROR = 0x00
ERR_NOT_SUPPORTED = 0x01
ERR_FAILED = 0x07
ERR_TIMEOUT = 0x09
ERR_BUFFER_EMPTY = 0x10

PROTOCOL_ISO15765 = 6
ISO15765_FRAME_PAD = 0x00000040
FLOW_CONTROL_FILTER = 0x03
TX_INDICATION = 0x00000008
START_OF_MESSAGE = 0x00000002

J2534_ERROR_NAMES = {
    STATUS_NOERROR: "STATUS_NOERROR",
    ERR_NOT_SUPPORTED: "ERR_NOT_SUPPORTED",
    0x02: "ERR_INVALID_CHANNEL_ID",
    0x03: "ERR_INVALID_PROTOCOL_ID",
    0x04: "ERR_NULL_PARAMETER",
    0x05: "ERR_INVALID_IOCTL_VALUE",
    0x06: "ERR_INVALID_FLAGS",
    ERR_FAILED: "ERR_FAILED",
    0x08: "ERR_DEVICE_NOT_CONNECTED",
    ERR_TIMEOUT: "ERR_TIMEOUT",
    0x0A: "ERR_INVALID_MSG",
    ERR_BUFFER_EMPTY: "ERR_BUFFER_EMPTY",
    0x11: "ERR_BUFFER_FULL",
}


class J2534Error(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(message)


class PassThruMsg(ctypes.Structure):
    _fields_ = [
        ("ProtocolID", c_ulong),
        ("RxStatus", c_ulong),
        ("TxFlags", c_ulong),
        ("Timestamp", c_ulong),
        ("DataSize", c_ulong),
        ("ExtraDataIndex", c_ulong),
        ("Data", ctypes.c_ubyte * 4128),
    ]


NRC_RESPONSE_PENDING = 0x78
# P2*max típico de KWP2000/UDS: 5 s por resposta 0x78.
PENDING_TIMEOUT_MS = 5000
MAX_PENDING = 10
MAX_DISCARDED = 20

RESPONSE_MATCH = "match"
RESPONSE_PENDING = "pending"
RESPONSE_OTHER = "other"


# Serviços OBD-II cuja resposta positiva repete o PID pedido (01 -> 41 pid, 02 -> 42 pid, 09 -> 49 pid).
OBD_PID_ECHO_SERVICES = {0x01, 0x02, 0x09}


def classify_response(resp: bytes, sid: int, request: bytes | None = None) -> str:
    """Relaciona uma resposta com o serviço pedido (sem interpretar dados).

    `match`: positiva (sid + 0x40) ou negativa final (7F sid nrc != 0x78).
    `pending`: 7F sid 78. `other`: qualquer outro frame.
    Com `request`, nos serviços OBD que repetem o PID, a positiva também precisa trazer o PID
    pedido: uma resposta atrasada de outro PID do mesmo serviço não pode ser aceita.
    """
    if not resp:
        return RESPONSE_OTHER
    if resp[0] == (sid + 0x40) & 0xFF:
        if (request is not None and sid in OBD_PID_ECHO_SERVICES and len(request) >= 2
                and (len(resp) < 2 or resp[1] != request[1])):
            return RESPONSE_OTHER
        return RESPONSE_MATCH
    if resp[0] == 0x7F and len(resp) >= 3 and resp[1] == sid:
        return RESPONSE_PENDING if resp[2] == NRC_RESPONSE_PENDING else RESPONSE_MATCH
    return RESPONSE_OTHER


def error_name(code: int) -> str:
    return J2534_ERROR_NAMES.get(code, f"UNKNOWN(0x{code:02X})")


def pack_can_id(can_id: int) -> bytes:
    return can_id.to_bytes(4, "big")


def payload_from_msg(msg: PassThruMsg) -> bytes:
    size = int(msg.DataSize)
    if size < 4:
        return b""
    return bytes(msg.Data[4:size])


def load_j2534_dll(dll_path: str):
    windll = getattr(ctypes, "WinDLL", None)
    if windll is None:
        raise J2534Error(ERR_FAILED, "J2534 requer ctypes.WinDLL (Windows)")
    try:
        lib = windll(dll_path)
    except OSError as exc:
        raise J2534Error(ERR_FAILED, f"falha ao carregar {dll_path}: {exc}") from exc
    _bind_prototypes(lib)
    return lib


def _bind_prototypes(lib) -> None:
    lib.PassThruOpen.argtypes = [c_void_p, POINTER(c_ulong)]
    lib.PassThruOpen.restype = c_ulong
    lib.PassThruClose.argtypes = [c_ulong]
    lib.PassThruClose.restype = c_ulong
    lib.PassThruConnect.argtypes = [c_ulong, c_ulong, c_ulong, c_ulong, POINTER(c_ulong)]
    lib.PassThruConnect.restype = c_ulong
    lib.PassThruDisconnect.argtypes = [c_ulong]
    lib.PassThruDisconnect.restype = c_ulong
    lib.PassThruReadMsgs.argtypes = [c_ulong, POINTER(PassThruMsg), POINTER(c_ulong), c_ulong]
    lib.PassThruReadMsgs.restype = c_ulong
    lib.PassThruWriteMsgs.argtypes = [c_ulong, POINTER(PassThruMsg), POINTER(c_ulong), c_ulong]
    lib.PassThruWriteMsgs.restype = c_ulong
    lib.PassThruStartMsgFilter.argtypes = [
        c_ulong, c_ulong, POINTER(PassThruMsg), POINTER(PassThruMsg),
        POINTER(PassThruMsg), POINTER(c_ulong),
    ]
    lib.PassThruStartMsgFilter.restype = c_ulong
    lib.PassThruStopMsgFilter.argtypes = [c_ulong, c_ulong]
    lib.PassThruStopMsgFilter.restype = c_ulong
    lib.PassThruGetLastError.argtypes = [POINTER(c_char)]
    lib.PassThruGetLastError.restype = c_ulong
    # Opcional: nem toda DLL exporta; ausência não é erro.
    read_version = getattr(lib, "PassThruReadVersion", None)
    if read_version is not None:
        read_version.argtypes = [c_ulong, POINTER(c_char), POINTER(c_char), POINTER(c_char)]
        read_version.restype = c_ulong


class J2534Device:
    data_source = "j2534"

    def __init__(
        self,
        dll_path: str,
        txid: int = 0x7E0,
        rxid: int = 0x7E8,
        baudrate: int = 500_000,
        loader=load_j2534_dll,
    ) -> None:
        self.dll_path = dll_path
        self.txid = txid
        self.rxid = rxid
        self.baudrate = baudrate
        self._loader = loader
        self._lib = None
        self._device_id = c_ulong(0)
        self._channel_id = c_ulong(0)
        self._filter_id = c_ulong(0)
        self._opened = False

    def open(self) -> None:
        self._lib = self._loader(self.dll_path)
        self._check(self._lib.PassThruOpen(None, byref(self._device_id)), "PassThruOpen")
        self._check(
            self._lib.PassThruConnect(
                self._device_id,
                PROTOCOL_ISO15765,
                0,
                self.baudrate,
                byref(self._channel_id),
            ),
            "PassThruConnect",
        )
        self._start_flow_filter()
        self._opened = True

    def reset_channel(self) -> None:
        """Desconecta e reconecta o canal (zera os filtros) SEM fechar o dispositivo.

        Fechar e reabrir o GD101 na mesma execução dá ERR_DEVICE_NOT_CONNECTED; só o canal é refeito.
        Volta ao par de IDs atual.
        """
        if not self._opened or self._lib is None:
            raise J2534Error(ERR_FAILED, "dispositivo J2534 não está aberto")
        if self._channel_id.value:
            self._lib.PassThruDisconnect(self._channel_id)       # filtro some junto; erro aqui não impede refazer
            self._channel_id = c_ulong(0)
        self._filter_id = c_ulong(0)
        self._check(
            self._lib.PassThruConnect(self._device_id, PROTOCOL_ISO15765, 0, self.baudrate,
                                      byref(self._channel_id)),
            "PassThruConnect",
        )
        self._start_flow_filter()

    def close(self) -> None:
        if self._lib is None:
            self._opened = False
            return
        if self._channel_id.value:
            self._lib.PassThruDisconnect(self._channel_id)
            self._channel_id = c_ulong(0)
        if self._device_id.value:
            self._lib.PassThruClose(self._device_id)
            self._device_id = c_ulong(0)
        self._opened = False

    def read_version(self) -> dict[str, str] | None:
        """PassThruReadVersion (firmware, DLL, API). Não envia nada no barramento.

        Devolve None se a DLL não exporta a função.
        """
        if not self._opened or self._lib is None:
            raise J2534Error(ERR_FAILED, "dispositivo J2534 não está aberto")
        fn = getattr(self._lib, "PassThruReadVersion", None)
        if fn is None:
            return None
        # J2534 04.04: cada string tem no máximo 80 caracteres.
        firmware, dll, api = ((c_char * 80)() for _ in range(3))
        self._check(fn(self._device_id, firmware, dll, api), "PassThruReadVersion")

        def text(buf) -> str:
            return bytes(buf).split(b"\x00", 1)[0].decode("ascii", "replace")

        return {"firmware": text(firmware), "dll": text(dll), "api": text(api)}

    def send_recv(
        self,
        data: bytes,
        timeout_ms: int = 200,
        pending_timeout_ms: int = PENDING_TIMEOUT_MS,
    ) -> bytes:
        """Envia `data` e devolve a resposta correspondente ao serviço.

        - `7F <sid> 78` (response pending) não é devolvido: a leitura continua
          com janela `pending_timeout_ms`, até `MAX_PENDING` vezes.
        - Frames de outro serviço (ex.: resposta atrasada a um request
          anterior que deu timeout) são descartados, até `MAX_DISCARDED`.
        - Cada leitura reinicia a janela; o tempo total pode passar de
          `timeout_ms` quando há pendings ou descartes.
        """
        if not self._opened or self._lib is None:
            raise J2534Error(ERR_FAILED, "dispositivo J2534 não está aberto")
        self._write(data, timeout_ms)
        if not data:
            return self._read_response(timeout_ms)
        sid = data[0]
        window = timeout_ms
        pending = discarded = 0
        while True:
            resp = self._read_response(window)
            kind = classify_response(resp, sid, data)
            if kind == RESPONSE_MATCH:
                return resp
            if kind == RESPONSE_PENDING:
                pending += 1
                if pending > MAX_PENDING:
                    raise J2534Error(
                        ERR_TIMEOUT,
                        f"serviço 0x{sid:02X}: {pending} respostas 0x78 seguidas",
                    )
                window = pending_timeout_ms
                continue
            discarded += 1
            if discarded > MAX_DISCARDED:
                raise J2534Error(
                    ERR_TIMEOUT,
                    f"serviço 0x{sid:02X}: {discarded} frames de outro serviço descartados",
                )

    def set_ids(self, txid: int, rxid: int) -> None:
        """Troca os CAN IDs do filtro de fluxo sem fechar o canal.

        Permite atender mais de um módulo (ex.: ECM 0x7E0/0x7E8 e TCM
        0x7E1/0x7E9) com um único PassThruOpen/PassThruConnect. Só leitura;
        não muda protocolo nem baudrate.
        """
        if not self._opened or self._lib is None:
            raise J2534Error(ERR_FAILED, "dispositivo J2534 não está aberto")
        if txid == self.txid and rxid == self.rxid:
            return
        if self._filter_id.value:
            self._check(
                self._lib.PassThruStopMsgFilter(self._channel_id, self._filter_id),
                "PassThruStopMsgFilter",
            )
            self._filter_id = c_ulong(0)
        self._start_flow_filter(txid, rxid)
        self.txid = txid
        self.rxid = rxid

    def _start_flow_filter(self, txid: int | None = None,
                           rxid: int | None = None) -> None:
        tx = self.txid if txid is None else txid
        rx = self.rxid if rxid is None else rxid
        mask = self._id_msg(0xFFFFFFFF)
        pattern = self._id_msg(rx)
        flow = self._id_msg(tx)
        filter_id = c_ulong(0)
        self._check(
            self._lib.PassThruStartMsgFilter(
                self._channel_id,
                FLOW_CONTROL_FILTER,
                byref(mask),
                byref(pattern),
                byref(flow),
                byref(filter_id),
            ),
            "PassThruStartMsgFilter",
        )
        self._filter_id = filter_id

    def _write(self, data: bytes, timeout_ms: int) -> None:
        msg = self._payload_msg(self.txid, data, tx=True)
        count = c_ulong(1)
        self._check(
            self._lib.PassThruWriteMsgs(self._channel_id, byref(msg), byref(count), timeout_ms),
            "PassThruWriteMsgs",
        )

    def _read_response(self, timeout_ms: int) -> bytes:
        deadline_chunks = max(1, timeout_ms)
        remaining = deadline_chunks
        while remaining > 0:
            chunk = min(50, remaining)
            msg = PassThruMsg()
            count = c_ulong(1)
            code = self._lib.PassThruReadMsgs(
                self._channel_id, byref(msg), byref(count), chunk,
            )
            remaining -= chunk
            if code == ERR_BUFFER_EMPTY:
                continue
            if code == ERR_TIMEOUT:
                raise J2534Error(code, error_name(code))
            if code != STATUS_NOERROR:
                self._raise(code, "PassThruReadMsgs")
            if msg.RxStatus & TX_INDICATION:
                continue
            if msg.RxStatus & START_OF_MESSAGE and payload_from_msg(msg) == b"":
                continue
            payload = payload_from_msg(msg)
            if payload:
                return payload
        raise J2534Error(ERR_TIMEOUT, error_name(ERR_TIMEOUT))

    def _payload_msg(self, can_id: int, data: bytes, tx: bool) -> PassThruMsg:
        msg = PassThruMsg()
        msg.ProtocolID = PROTOCOL_ISO15765
        msg.TxFlags = ISO15765_FRAME_PAD if tx else 0
        packed = pack_can_id(can_id) + data
        msg.DataSize = len(packed)
        for i, byte in enumerate(packed):
            msg.Data[i] = byte
        return msg

    def _id_msg(self, can_id: int) -> PassThruMsg:
        msg = PassThruMsg()
        msg.ProtocolID = PROTOCOL_ISO15765
        packed = pack_can_id(can_id)
        msg.DataSize = 4
        for i, byte in enumerate(packed):
            msg.Data[i] = byte
        return msg

    def _check(self, code: int, op: str) -> None:
        if code != STATUS_NOERROR:
            self._raise(code, op)

    def _raise(self, code: int, op: str) -> None:
        detail = error_name(code)
        if self._lib is not None:
            buf = (c_char * 256)()
            try:
                self._lib.PassThruGetLastError(buf)
                text = bytes(buf).split(b"\x00", 1)[0].decode("ascii", "replace")
                if text:
                    detail = f"{detail}: {text}"
            except Exception:  # noqa: BLE001
                pass
        raise J2534Error(code, f"{op}: {detail}")

    def __enter__(self) -> "J2534Device":
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
