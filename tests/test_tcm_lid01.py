"""Decoder puro do LID 0x01 do TCM: campos confirmados, estimados e crus."""
from __future__ import annotations

import unittest
from pathlib import Path

from openscan_obd.gateway.tcm_lid01 import TCM_LID01_LEN, decode_tcm_lid01

FIXTURE = Path(__file__).parent / "fixtures" / "tcm_lid01_raw.hex"
BASE = bytes.fromhex(FIXTURE.read_text().strip())


def with_bytes(**changes: int) -> bytes:
    b = bytearray(BASE)
    for k, v in changes.items():
        b[int(k[1:])] = v
    return bytes(b)


class TestDecodeTcmLid01(unittest.TestCase):
    def test_fixture_has_expected_length(self) -> None:
        self.assertEqual(len(BASE), TCM_LID01_LEN)

    def test_rpm_is_word_over_eight(self) -> None:
        out = decode_tcm_lid01(with_bytes(b6=0x0B, b7=0x18))
        self.assertEqual(out["ENG_SPEED_rpm"], 355.0)

    def test_gear_from_high_nibble_of_b54(self) -> None:
        for nibble, gear in ((0x1, "P"), (0x4, "N"), (0x8, "D"), (0x2, "R")):
            with self.subTest(gear=gear):
                self.assertEqual(decode_tcm_lid01(with_bytes(b54=nibble << 4))["gear"], gear)

    def test_unknown_gear_nibble_is_none_and_keeps_raw(self) -> None:
        out = decode_tcm_lid01(with_bytes(b54=0x9F))
        self.assertIsNone(out["gear"])
        self.assertEqual(out["gear_raw"], "0x9F")

    def test_reverse_flag(self) -> None:
        self.assertEqual(decode_tcm_lid01(with_bytes(b40=0x5A))["REV_b40"], "REVERSE")
        self.assertEqual(decode_tcm_lid01(with_bytes(b40=0xFE))["REV_b40"], "NOT_REVERSE")

    def test_atf_is_marked_estimated_not_confirmed(self) -> None:
        # Decisão 2026-11-15: ATF [30] só tem a tabela do ESM como referência.
        out = decode_tcm_lid01(with_bytes(b30=83))
        self.assertEqual(out["atf_temp_c_estimated"], 40.0)
        self.assertNotIn("atf_temp_c", out)

    def test_raw_hex_preserved(self) -> None:
        self.assertEqual(decode_tcm_lid01(BASE)["raw_hex"], BASE.hex())

    def test_short_payload_raises(self) -> None:
        with self.assertRaises(ValueError):
            decode_tcm_lid01(BASE[:-1])


if __name__ == "__main__":
    unittest.main()
