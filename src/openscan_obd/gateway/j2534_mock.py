"""Mock J2534 com a mesma superfície de J2534Device, para testes offline.

Não abre hardware. As respostas de ReadDataByLocalIdentifier 0x21 / LID 0x01
vêm de um hex gravado no ECM do veículo de teste (B16), não de um payload
inventado no formato B17 do SDD.
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_LID01_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "ecm_lid01_raw.hex"
)

# LID 0x01 do TCM (69 bytes) gravado em campo: tests/fixtures/lid01_field_20261023.json
# captura "seletor_P" (2026-10-23), extraída para hex em tcm_lid01_raw.hex.
DEFAULT_TCM_LID01_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "tcm_lid01_raw.hex"
)

TCM_TX = 0x7E1
TCM_RX = 0x7E9

# Respostas de modo 01 (OBD-II) gravadas do ECM do veículo de teste (B16):
# logs/full_scan_20261115_184513.txt — ECT 94 C (41 05 86), RPM 710 (41 0C 0B 18),
# VSP 0 (41 0D 00), TPS 12,5 % (41 11 20), tensão 14,3 V (41 42 37 AD) e os bitmaps de
# PIDs suportados 01 00 / 01 20 / 01 40 (mesmo arquivo).
OBD01_FIXTURE: dict[int, bytes] = {
    0x00: bytes.fromhex("4100be1fb813"),
    0x20: bytes.fromhex("412080058001"),
    0x40: bytes.fromhex("41407e100000"),
    0x42: bytes.fromhex("414237ad"),
    0x05: bytes.fromhex("410586"),
    0x0C: bytes.fromhex("410c0b18"),
    0x0D: bytes.fromhex("410d00"),
    0x11: bytes.fromhex("411120"),
    # SINTÉTICOS (valores plausíveis em marcha lenta; NÃO vieram do carro). O bitmap acima é real
    # e declara estes PIDs; a leitura ao vivo deles ainda não foi feita no veículo.
    0x03: bytes.fromhex("41030200"),
    0x04: bytes.fromhex("410440"),
    0x06: bytes.fromhex("41067f"),
    0x07: bytes.fromhex("410783"),
    0x0E: bytes.fromhex("410e98"),
    0x0F: bytes.fromhex("410f4f"),
    0x10: bytes.fromhex("41100190"),
    0x14: bytes.fromhex("41145aff"),
    0x15: bytes.fromhex("41157aff"),
    0x1F: bytes.fromhex("411f012c"),
    0x43: bytes.fromhex("41430040"),
    0x44: bytes.fromhex("41448000"),
    0x46: bytes.fromhex("414644"),
    0x4C: bytes.fromhex("414c20"),
}


def load_hex_fixture(path: Path) -> bytes:
    """Lê bytes hex (com ou sem espaços/newlines)."""
    text = path.read_text(encoding="ascii").strip()
    cleaned = "".join(text.split())
    if not cleaned:
        raise ValueError(f"fixture hex vazia: {path}")
    return bytes.fromhex(cleaned)


class J2534DeviceMock:
    """Interface: open(), close(), send_recv(data, timeout_ms) -> bytes."""

    data_source = "recorded_fixture"

    def __init__(
        self,
        fixture_path: str | Path | None = None,
        lid01_payload: bytes | None = None,
        tcm_fixture_path: str | Path | None = None,
        tcm_lid01_payload: bytes | None = None,
        obd01: dict[int, bytes] | None = None,
    ) -> None:
        path = Path(fixture_path) if fixture_path is not None else DEFAULT_LID01_FIXTURE
        if lid01_payload is None:
            lid01_payload = load_hex_fixture(path)
        self._lid01_payload = lid01_payload
        tcm_path = (
            Path(tcm_fixture_path) if tcm_fixture_path is not None
            else DEFAULT_TCM_LID01_FIXTURE
        )
        if tcm_lid01_payload is None:
            tcm_lid01_payload = load_hex_fixture(tcm_path)
        self._tcm_lid01_payload = tcm_lid01_payload
        # PIDs de modo 01 respondidos; `{}` simula um ECM sem OBD (força o fallback do LID).
        self._obd01 = OBD01_FIXTURE if obd01 is None else obd01
        self._tx = 0x7E0
        self._rx = 0x7E8
        self._opened = False

    def open(self) -> None:
        self._opened = True

    def close(self) -> None:
        self._opened = False

    def set_ids(self, txid: int, rxid: int) -> None:
        """Mesma superfície de J2534Device.set_ids: só registra os IDs atuais."""
        self._tx = txid
        self._rx = rxid

    def send_recv(self, data: bytes, timeout_ms: int = 200) -> bytes:
        if not self._opened:
            raise RuntimeError("J2534DeviceMock não está aberto")
        if timeout_ms <= 0:
            raise TimeoutError("ERR_TIMEOUT")
        if not data:
            raise TimeoutError("ERR_BUFFER_EMPTY")
        service = data[0]
        if service == 0x10:
            session = data[1] if len(data) > 1 else 0x00
            return bytes([0x50, session])
        if service == 0x3E:
            return b"\x7e\x00"
        if service == 0x21:
            lid = data[1] if len(data) > 1 else 0x00
            if lid == 0x01:
                payload = (
                    self._tcm_lid01_payload if self._tx == TCM_TX
                    else self._lid01_payload
                )
                if payload[:1] == b"\x01":
                    return b"\x61" + payload
                return b"\x61\x01" + payload
            return bytes([0x7F, 0x21, 0x31])
        if service == 0x01 and len(data) >= 2:
            pid = data[1]
            if pid in self._obd01:
                return self._obd01[pid]
            return bytes([0x7F, 0x01, 0x11])
        if service == 0x09 and len(data) >= 2 and data[1] == 0x00:
            return bytes.fromhex("490014000000")    # 09 00 gravado: só 04 e 06 suportados
        if service == 0x17:
            if self._tx == TCM_TX:
                # Gravado no TCM do Sentra B16 em 2026-11-16 (17 FF 00): P0725, U1000, P1722.
                return bytes.fromhex("57030725f1d000a71722f1")
            return bytes([0x7F, 0x17, 0x12])
        if service in (0x03, 0x07):
            # Gravado no carro em 2026-11-15 (logs/full_scan_20261115_184513.txt):
            # nenhum DTC confirmado nem pendente (43 00 / 47 00).
            return bytes([service + 0x40, 0x00])
        return bytes([0x7F, service, 0x11])
