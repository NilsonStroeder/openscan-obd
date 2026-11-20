"""PIDs de modo 01 adicionados para o dashboard (SAE J1979), decodificados offline."""
from __future__ import annotations

import unittest

from openscan_obd.obd2 import decode_live_data


def dec(hexstr: str):
    return decode_live_data(bytes.fromhex(hexstr))


class TestExtraPids(unittest.TestCase):
    def test_short_term_fuel_trim(self) -> None:
        self.assertEqual(dec("410680")[1:3], (0.0, "%"))
        self.assertAlmostEqual(dec("4106ff")[1], 99.2188, places=3)
        self.assertAlmostEqual(dec("410600")[1], -100.0)

    def test_long_term_fuel_trim(self) -> None:
        self.assertAlmostEqual(dec("410780")[1], 0.0)
        self.assertEqual(dec("410780")[2], "%")

    def test_timing_advance(self) -> None:
        self.assertEqual(dec("410e80")[1:3], (0.0, "°"))
        self.assertEqual(dec("410e90")[1], 8.0)
        self.assertEqual(dec("410e00")[1], -64.0)

    def test_o2_sensor_voltage_uses_first_byte(self) -> None:
        self.assertEqual(dec("4114c8ff")[1:3], (1.0, "V"))     # 0xC8/200
        self.assertEqual(dec("4115 64ff".replace(" ", ""))[1], 0.5)

    def test_absolute_load(self) -> None:
        self.assertAlmostEqual(dec("414300ff")[1], 100.0)
        self.assertAlmostEqual(dec("414300fe")[1], 99.6078, places=3)
        self.assertEqual(dec("41430000")[1], 0.0)

    def test_two_byte_pid_with_one_byte_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            dec("411400")


if __name__ == "__main__":
    unittest.main()


class TestPidsDeclaredByTheRealEcm(unittest.TestCase):
    """Bitmap real de 2026-11-15 (01 00/20/40) declara 1F, 44, 46 e 4C; antes não eram lidos."""

    def test_run_time_since_start(self) -> None:
        self.assertEqual(dec("411f0000")[1:3], (0, "s"))
        self.assertEqual(dec("411f012c")[1], 300)

    def test_commanded_equivalence_ratio_lambda(self) -> None:
        self.assertAlmostEqual(dec("41448000")[1], 1.0)          # 0x8000/32768
        self.assertEqual(dec("41448000")[2], "λ")
        self.assertAlmostEqual(dec("41440000")[1], 0.0)

    def test_commanded_throttle_actuator(self) -> None:
        self.assertEqual(dec("414c00")[1:3], (0.0, "%"))
        self.assertAlmostEqual(dec("414cff")[1], 100.0)

    def test_ambient_air_temperature(self) -> None:
        self.assertEqual(dec("464f".replace("46", "4146"))[1:3], (39, "C"))   # 0x4F - 40
