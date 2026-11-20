"""KWP SID 0x17 (ReadStatusOfDiagnosticTroubleCodes) no TCM: decodificação de hipótese."""
from __future__ import annotations

import unittest

from openscan_obd.gateway.kwp_dtc17 import decode_status_of_dtc, dtc_text

# Resposta crua do TCM do Sentra B16 em 2026-11-16 (logs/probe_dtc_20261116_134152.json, H3).
REAL = bytes.fromhex("57030725f1d000a71722f1")


class TestDtcText(unittest.TestCase):
    def test_sae_j2012_letters_and_digits(self) -> None:
        self.assertEqual(dtc_text(0x0725), "P0725")
        self.assertEqual(dtc_text(0xD000), "U1000")
        self.assertEqual(dtc_text(0x1722), "P1722")
        self.assertEqual(dtc_text(0x4123), "C0123")
        self.assertEqual(dtc_text(0x8001), "B0001")


class TestDecodeStatusOfDtc(unittest.TestCase):
    def test_real_tcm_reply(self) -> None:
        r = decode_status_of_dtc(REAL)
        self.assertEqual(r["count"], 3)
        self.assertEqual([c["code"] for c in r["codes"]], ["P0725", "U1000", "P1722"])
        self.assertEqual([c["status_byte"] for c in r["codes"]], ["f1", "a7", "f1"])
        self.assertEqual(r["raw"], REAL.hex())

    def test_status_byte_is_kept_raw_not_interpreted(self) -> None:
        for c in decode_status_of_dtc(REAL)["codes"]:
            self.assertEqual(set(c), {"code", "status_byte", "raw"})

    def test_empty_list_is_not_a_clean_bill_of_health(self) -> None:
        r = decode_status_of_dtc(bytes.fromhex("5700"))
        self.assertEqual(r["codes"], [])
        self.assertIn("não prova", r["note"])

    def test_malformed_replies_raise(self) -> None:
        for bad in ("", "57", "5703", "5703 0725f1".replace(" ", ""), "6103 0725f1".replace(" ", "")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    decode_status_of_dtc(bytes.fromhex(bad))


if __name__ == "__main__":
    unittest.main()
