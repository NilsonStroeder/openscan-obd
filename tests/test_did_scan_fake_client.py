"""
Testa a categorização de resultados em did_scan.scan_dids() contra um
client UDS SIMULADO, sem precisar de hardware nem DLL J2534 real.

Confirma que cada tipo de resposta cai no status certo:
  - dado válido          -> "ok"
  - NegativeResponseException -> "negado"
  - TimeoutException     -> "sem_resposta"
  - bytes recebidos -> preservados como hex em "ok"
  - qualquer outra exceção -> "erro"

Roda com: python3 -m unittest tests.test_did_scan_fake_client -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from udsoncan.exceptions import NegativeResponseException, TimeoutException  # noqa: E402

from openscan_obd import did_scan  # noqa: E402
from openscan_obd.transport import RawBytesDidCodec  # noqa: E402


class _FakeResponse:
    def __init__(self, code: int, code_name: str) -> None:
        self.code = code
        self.code_name = code_name
        # NegativeResponseException.make_msg() acessa .service também —
        # descoberto rodando o construtor real contra um objeto sem esse
        # atributo (AttributeError). None é tratado como "sem serviço".
        self.service = None


class _FakeClient:
    """Simula o client do udsoncan, decidindo o comportamento pelo DID pedido."""

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def read_data_by_identifier_first(self, did: int):
        if did == 0xF190:
            return "FAKEVIN1234567890"
        if did == 0xF191:
            raise NegativeResponseException(_FakeResponse(0x33, "securityAccessDenied"))
        if did == 0xF192:
            raise TimeoutException("sem resposta simulada")
        if did == 0xF193:
            return bytes.fromhex("001234")
        raise RuntimeError("erro genérico simulado")


def _fake_make_j2534_client(dll_path, rxid, txid, baudrate=500_000, timeout=2.0):
    return _FakeClient()


class TestScanDidsCategorization(unittest.TestCase):
    def test_each_did_gets_expected_status(self) -> None:
        with mock.patch("openscan_obd.transport.make_j2534_client", _fake_make_j2534_client), \
             mock.patch("openscan_obd.did_scan.time.sleep"):
            results = did_scan.scan_dids(
                dll_path="fake.dll", rxid=0x7E9, txid=0x7E1, start=0xF190, end=0xF194, delay=0.0
            )

        by_did = {r.did: r for r in results}
        self.assertEqual(by_did[0xF190].status, "ok")
        self.assertEqual(by_did[0xF191].status, "negado")
        self.assertIn("securityAccessDenied", by_did[0xF191].detail)
        self.assertEqual(by_did[0xF192].status, "sem_resposta")
        self.assertEqual(by_did[0xF193].status, "ok")
        self.assertEqual(by_did[0xF193].detail, "001234")
        self.assertEqual(by_did[0xF194].status, "erro")


class TestRawBytesDidCodec(unittest.TestCase):
    def test_codec_preserves_variable_length_payload(self) -> None:
        codec = RawBytesDidCodec()
        payload = bytes.fromhex("001234aabb")
        self.assertEqual(codec.decode(payload), payload)
        with self.assertRaises(codec.ReadAllRemainingData):
            len(codec)


if __name__ == "__main__":
    unittest.main()
