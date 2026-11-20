"""
Testa os decoders puros do Tier A (obd2.py) com dados sinteticos — sem
hardware. Valida a logica que a sintaxe (py_compile) nao pega.

Roda: python3 -m unittest tests.test_obd2_decoders -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd import obd2  # noqa: E402


class TestDtcDecode(unittest.TestCase):
    def test_known_codes(self) -> None:
        # Exemplos verificados do formato SAE J2012.
        self.assertEqual(obd2.decode_dtc(0x01, 0x33), "P0133")
        self.assertEqual(obd2.decode_dtc(0x00, 0x00), "P0000")
        # Primeiros 2 bits selecionam a letra:
        self.assertEqual(obd2.decode_dtc(0x41, 0x30)[0], "C")  # 01xxxxxx -> C
        self.assertEqual(obd2.decode_dtc(0x81, 0x30)[0], "B")  # 10xxxxxx -> B
        self.assertEqual(obd2.decode_dtc(0xC1, 0x30)[0], "U")  # 11xxxxxx -> U
        self.assertEqual(obd2.decode_dtc(0x01, 0x30), "P0130")

    def test_u0101_tcm_lost_comm(self) -> None:
        # U0101 (perda de comunicacao com TCM) — relevante pro nosso carro.
        # U = 11, 0, 1, 01 -> byte1 = 11_00_0001 = 0xC1, byte2 = 0x01
        self.assertEqual(obd2.decode_dtc(0xC1, 0x01), "U0101")

    def test_dtc_list_skips_padding(self) -> None:
        # Dois DTCs reais + um par de preenchimento 0x0000.
        payload = bytes([0x01, 0x33, 0xC1, 0x01, 0x00, 0x00])
        self.assertEqual(obd2.decode_dtc_list(payload), ["P0133", "U0101"])

    def test_dtc_list_empty(self) -> None:
        self.assertEqual(obd2.decode_dtc_list(bytes([0x00, 0x00])), [])

    def test_dtc_list_rejects_incomplete_pair(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_dtc_list(bytes([0x01]))

    def test_dtc_list_with_can_count_byte(self) -> None:
        # ISO 15765-4: 1 byte de contagem + pares
        self.assertEqual(obd2.decode_dtc_list(bytes([0x02, 0x01, 0x33, 0xC1, 0x01])),
                         ["P0133", "U0101"])

    def test_dtc_list_count_zero(self) -> None:
        self.assertEqual(obd2.decode_dtc_list(bytes([0x00])), [])

    def test_dtc_list_rejects_count_mismatch(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_dtc_list(bytes([0x02, 0x01, 0x33]))

    def test_dtc_response_validates_positive_byte(self) -> None:
        self.assertEqual(obd2.decode_dtc_response(bytes([0x47, 0x01, 0x01, 0x33]), 0x07),
                         ["P0133"])
        with self.assertRaises(ValueError):
            obd2.decode_dtc_response(bytes([0x43, 0x00]), 0x07)
        with self.assertRaises(ValueError):
            obd2.decode_dtc_response(None)


class TestSupportedPids(unittest.TestCase):
    def test_mode01_pid00_bitmap(self) -> None:
        # BE 1F A8 13 -> exemplo classico de bitmap (Wikipedia OBD-II PIDs)
        pids = obd2.decode_supported_pids(bytes.fromhex("4100be1fa813"))
        self.assertEqual(pids, [0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x0C, 0x0D,
                                0x0E, 0x0F, 0x10, 0x11, 0x13, 0x15, 0x1C, 0x1F, 0x20])

    def test_offset_bitmap_and_mode09(self) -> None:
        self.assertEqual(obd2.decode_supported_pids(bytes.fromhex("412080000001")), [0x21, 0x40])
        self.assertEqual(obd2.decode_supported_pids(bytes.fromhex("490054000000"), mode=0x09),
                         [0x02, 0x04, 0x06])

    def test_bitmap_rejects_wrong_length_or_mode(self) -> None:
        for raw in ("4100be1f", "4105be1fa813", "7f0112", "4900be1fa813"):
            with self.assertRaises(ValueError):
                obd2.decode_supported_pids(bytes.fromhex(raw))


class TestLiveData(unittest.TestCase):
    def test_rpm(self) -> None:
        # 41 0C 1A F8 -> (0x1A*256 + 0xF8)/4 = (6656+248)/4 = 1726 rpm
        pid, val, unit, name = obd2.decode_live_data(bytes([0x41, 0x0C, 0x1A, 0xF8]))
        self.assertEqual(pid, 0x0C)
        self.assertAlmostEqual(val, 1726.0)
        self.assertEqual(unit, "rpm")

    def test_coolant_temp(self) -> None:
        # 41 05 5A -> 0x5A(90) - 40 = 50 C
        pid, val, unit, name = obd2.decode_live_data(bytes([0x41, 0x05, 0x5A]))
        self.assertEqual(val, 50)
        self.assertEqual(unit, "C")

    def test_speed(self) -> None:
        pid, val, unit, name = obd2.decode_live_data(bytes([0x41, 0x0D, 0x32]))
        self.assertEqual(val, 50)  # 0x32 = 50 km/h

    def test_module_voltage(self) -> None:
        # 41 42 33 9E -> (0x33*256 + 0x9E)/1000 = (13056+158)/1000 = 13.214 V
        pid, val, unit, name = obd2.decode_live_data(bytes([0x41, 0x42, 0x33, 0x9E]))
        self.assertAlmostEqual(val, 13.214)
        self.assertEqual(unit, "V")

    def test_unknown_pid_raises(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_live_data(bytes([0x41, 0xAB, 0x00]))

    def test_short_data_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_live_data(bytes([0x41, 0x0C, 0x1A]))  # RPM precisa de 2 bytes

    def test_malformed_raises(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_live_data(bytes([0x7F, 0x01]))  # resposta negativa, nao 0x41


class TestVin(unittest.TestCase):
    def test_vin_decode(self) -> None:
        vin_ascii = b"3N1AB6AP7BL000001"  # 17 chars, estilo Sentra
        resp = bytes([0x49, 0x02, 0x01]) + vin_ascii
        self.assertEqual(obd2.decode_vin(resp), "3N1AB6AP7BL000001")

    def test_vin_strips_padding_nonascii(self) -> None:
        resp = bytes([0x49, 0x02, 0x01, 0x00, 0x00]) + b"1HGCM82633A004352"
        self.assertEqual(obd2.decode_vin(resp), "1HGCM82633A004352")


class TestVinLength(unittest.TestCase):
    def test_vin_without_characters_raises(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_vin(bytes([0x49, 0x02, 0x01]))

    def test_truncated_vin_raises(self) -> None:
        with self.assertRaises(ValueError):
            obd2.decode_vin(bytes([0x49, 0x02, 0x01]) + b"3N1AB6AP7")


class TestBuildRequest(unittest.TestCase):
    def test_build(self) -> None:
        self.assertEqual(obd2.build_request(0x01, 0x0C), b"\x01\x0c")
        self.assertEqual(obd2.build_request(0x03), b"\x03")


class TestReadDtcsRunner(unittest.TestCase):
    """Testa o runner read_dtcs com um client simulado (sem hardware)."""

    class FakeConn:
        def __init__(self, response: bytes) -> None:
            self._response = response
            self.sent: list[bytes] = []

        def send(self, data: bytes) -> None:
            self.sent.append(data)

        def wait_frame(self) -> bytes:
            return self._response

    def test_reads_and_decodes(self) -> None:
        # 43 0133 C101 0000 -> modo 03, 2 DTCs + preenchimento.
        fake = self.FakeConn(bytes([0x43, 0x01, 0x33, 0xC1, 0x01, 0x00, 0x00]))
        dtcs = obd2.read_dtcs(fake, mode=obd2.MODE_STORED_DTC)
        self.assertEqual(dtcs, ["P0133", "U0101"])
        self.assertEqual(fake.sent, [b"\x03"])

    def test_reads_dtc_without_count_byte(self) -> None:
        fake = self.FakeConn(bytes([0x43, 0x01, 0x33]))
        self.assertEqual(obd2.read_dtcs(fake), ["P0133"])

    def test_wrong_response_raises(self) -> None:
        fake = self.FakeConn(bytes([0x7F, 0x03, 0x11]))  # resposta negativa
        with self.assertRaises(ValueError):
            obd2.read_dtcs(fake)


if __name__ == "__main__":
    unittest.main()
