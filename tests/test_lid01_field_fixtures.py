"""Observacoes offline sobre as 14 capturas reais do LID 0x01 (2026-10-23).

Estes testes REGISTRAM fatos dos dados (nao confirmam significado de bytes).
Servem para impedir que o doc volte a afirmar algo que os payloads contradizem.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "lid01_field_20261023.json"


def _caps() -> dict[str, bytes]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))["captures"]
    return {c["label"]: bytes.fromhex(c["hex"]) for c in data}


class TestFieldCaptures(unittest.TestCase):
    def test_sizes_and_markers(self) -> None:
        caps = _caps()
        self.assertEqual(len(caps), 14)
        for name, b in caps.items():
            self.assertEqual(len(b), 69, name)
            self.assertEqual(b[0], 0x01, name)
            self.assertEqual(b[68], 0x5F, name)

    def test_word67_div8_engine_off_and_cruising(self) -> None:
        caps = _caps()
        rpm = lambda b: ((b[6] << 8) | b[7]) / 8
        self.assertLess(rpm(caps["frio_manha"]), 5)           # motor desligado
        self.assertAlmostEqual(rpm(caps["cruising_60"]), 1380.9, places=1)
        self.assertAlmostEqual(rpm(caps["cruising_80"]), 1540.8, places=1)

    def test_byte15_tracks_byte6_within_one(self) -> None:
        for name, b in _caps().items():
            self.assertLessEqual(abs(b[15] - b[6]), 1, name)

    def test_byte31_mirrors_byte6_only_in_cruising(self) -> None:
        caps = _caps()
        for name in ("cruising_60", "cruising_80", "tcc_80kmh"):
            self.assertEqual(caps[name][31], caps[name][6], name)
        for name in ("seletor_P", "seletor_N", "rpm1000_P", "rpm2000_P", "accel25_D"):
            self.assertNotEqual(caps[name][31], caps[name][6], name)

    def test_bytes_3_4_11_12_move_with_speed(self) -> None:
        caps = _caps()
        self.assertEqual((caps["seletor_P"][3], caps["seletor_P"][4]), (1, 0))
        self.assertEqual((caps["arranque_2"][3], caps["arranque_2"][4]), (3, 3))
        self.assertEqual((caps["cruising_60"][3], caps["cruising_60"][4]), (56, 57))
        self.assertEqual((caps["cruising_80"][3], caps["cruising_80"][4]), (77, 77))
        self.assertEqual((caps["tcc_80kmh"][3], caps["tcc_80kmh"][4]), (77, 77))
        for name in ("cruising_60", "cruising_80", "tcc_80kmh"):
            self.assertEqual(caps[name][3], caps[name][11], name)
            self.assertEqual(caps[name][4], caps[name][12], name)

    def test_bytes_19_22_are_not_vehicle_speed(self) -> None:
        caps = _caps()
        # a 77 km/h (bytes 3,4) com lock-up tentado, [19-22] ficou em zero
        self.assertEqual(list(caps["tcc_80kmh"][19:23]), [0, 0, 0, 0])
        # a ~3 km/h (arranque_2) ja vale ~20
        self.assertEqual(list(caps["arranque_2"][19:23]), [20, 20, 20, 21])

    def test_atf_count_never_rises_during_session(self) -> None:
        caps = _caps()
        order = ["frio_manha", "seletor_P", "seletor_N", "seletor_D", "seletor_R",
                 "rpm1000_P", "rpm2000_P", "accel25_D", "accel50_D", "arranque_1",
                 "arranque_2", "cruising_60", "cruising_80", "tcc_80kmh"]
        counts = [caps[n][9] for n in order]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertEqual((counts[0], counts[-1]), (175, 130))

    def test_bytes_23_25_stopped_selector_codes(self) -> None:
        caps = _caps()
        self.assertEqual(list(caps["seletor_P"][23:26]), [1, 1, 1])
        self.assertEqual(list(caps["seletor_D"][23:26]), [6, 6, 6])
        self.assertEqual(list(caps["seletor_R"][23:26]), [5, 5, 5])
        # nao e um codigo limpo em D com acelerador/movimento:
        self.assertEqual(list(caps["accel25_D"][23:26]), [0, 0, 0])
        self.assertEqual(list(caps["accel50_D"][23:26]), [252, 251, 252])
        self.assertEqual(list(caps["cruising_60"][23:26]), [5, 8, 6])


if __name__ == "__main__":
    unittest.main()
