"""Decoder ECM LID 0x01 — fórmulas do SDD, testadas offline sem veículo."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openscan_obd.gateway.decoder import decode_ecm_lid01  # noqa: E402
from openscan_obd.gateway.j2534_mock import load_hex_fixture  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ecm_lid01_raw.hex"


def _sdd_example_frame() -> bytes:
    """Payload sintético invertendo as fórmulas do SDD — não é captura de campo."""
    rpm = (68).to_bytes(2, "big")       # 68 * 12.5 = 850
    vsp = (0).to_bytes(2, "big")         # 0 / 100 = 0
    tps = bytes([128])                  # 128 * 100 / 255
    ect = bytes([128])                  # 88 °C
    iat = bytes([65])                   # 25 °C
    inj = (250).to_bytes(2, "big")       # 2.50 ms
    ign = bytes([148])                  # (148 - 128) * 0.5 = 10.0
    o2 = bytes([45])
    stft = bytes([128])                 # 0 %
    ltft = bytes([128])                 # 0 %
    return rpm + vsp + tps + ect + iat + inj + ign + o2 + stft + ltft


class TestDecodeEcmLid01(unittest.TestCase):
    def test_sdd_formulas(self) -> None:
        decoded = decode_ecm_lid01(_sdd_example_frame())
        self.assertEqual(decoded["rpm"], 850.0)
        self.assertEqual(decoded["vsp"], 0.0)
        self.assertAlmostEqual(decoded["tps"], 128 * 100 / 255)
        self.assertEqual(decoded["ect"], 88)
        self.assertEqual(decoded["iat"], 25)
        self.assertAlmostEqual(decoded["inj_pw"], 2.50)
        self.assertEqual(decoded["ign_adv"], 10.0)
        self.assertAlmostEqual(decoded["o2s1"], 45 * 4.96 / 255)
        self.assertEqual(decoded["stft"], 0.0)
        self.assertEqual(decoded["ltft"], 0.0)
        self.assertFalse(decoded["verified"])

    def test_short_recorded_b16_frame_is_rejected(self) -> None:
        recorded = load_hex_fixture(FIXTURE)
        if recorded[:1] == b"\x01":
            recorded = recorded[1:]
        with self.assertRaises(ValueError):
            decode_ecm_lid01(recorded)

    def test_too_short_raises_without_index_error(self) -> None:
        with self.assertRaises(ValueError):
            decode_ecm_lid01(b"\x00" * 12)


if __name__ == "__main__":
    unittest.main()
