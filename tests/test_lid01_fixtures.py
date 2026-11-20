"""Testes offline com snapshots reais do LID 0x01 do TCM (sem carro).

Registram a evidencia de que WORD_BE[6,7] / 8 acompanha a rotacao do MOTOR
(hipotese revisada em 2026-10-23, ver docs/cvt_lid01_decoder.md) e que
byte[15] e espelho do byte[6]. Sao observacoes, nao confirmacao de protocolo.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "lid01_snapshots.json"


def _load() -> dict[str, dict]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["snapshots"]


class TestLid01Snapshots(unittest.TestCase):
    def test_payload_size(self) -> None:
        for name, snap in _load().items():
            b = bytes.fromhex(snap["hex"])
            self.assertEqual(len(b), 69, name)
            self.assertEqual(b[0], 0x01, name)
            self.assertEqual(b[68], 0x5F, name)

    def test_word67_div8_tracks_engine_rpm(self) -> None:
        for name, snap in _load().items():
            b = bytes.fromhex(snap["hex"])
            rpm = ((b[6] << 8) | b[7]) / 8
            ref = snap["rpm_motor_referencia"]
            self.assertLess(abs(rpm - ref) / ref, 0.05, f"{name}: {rpm} vs {ref}")

    def test_byte15_mirrors_byte6(self) -> None:
        for name, snap in _load().items():
            b = bytes.fromhex(snap["hex"])
            self.assertEqual(b[15], b[6], name)

    def test_confirmed_fields_in_snapshots(self) -> None:
        snaps = _load()
        for name, snap in snaps.items():
            b = bytes.fromhex(snap["hex"])
            self.assertIn(b[23], (0x01, 0x02), name)  # P/N=1 (2 no snapshot acelerado)
        b = bytes.fromhex(snaps["marcha_lenta"]["hex"])
        self.assertEqual(b[9], 124)  # ATF COUNT 124 -> 60 C
        self.assertAlmostEqual(((b[36] << 8) | b[37]) / 96, 176.4, places=1)

    def test_observations_that_contradict_field_notes(self) -> None:
        """Observacoes dos 2 snapshots (carro parado em P). Registram fatos,
        nao interpretam: bytes[19-22] sobem so por acelerar o motor; b[31]
        nao espelha b[6]."""
        snaps = _load()
        idle = bytes.fromhex(snaps["marcha_lenta"]["hex"])
        rev = bytes.fromhex(snaps["acelerado"]["hex"])
        self.assertEqual(list(idle[19:23]), [0, 0, 0, 0])
        self.assertEqual(list(rev[19:23]), [23, 23, 23, 24])
        self.assertNotEqual(idle[31], idle[6])
        self.assertNotEqual(rev[31], rev[6])


if __name__ == "__main__":
    unittest.main()
