"""analisar_logs.py — análises offline com payloads sintéticos (sem veículo)."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import analisar_logs as al  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "lid01_field_20261023.json"
CAPS = {c["label"]: bytes.fromhex(c["hex"])
        for c in json.loads(FIXTURE.read_text(encoding="utf-8"))["captures"]}
BASE = CAPS["seletor_P"]


def payload(base: bytes = BASE, **changes: int) -> bytes:
    """Copia o payload real e troca bytes: payload(b3=10, b9=50)."""
    b = bytearray(base)
    for k, v in changes.items():
        b[int(k[1:])] = v & 0xFF
    return bytes(b)


def corr_sample(i: int, p: bytes, src: str = "correlated_x.json", **obd) -> al.Sample:
    return al.Sample(source=src, kind="correlated", label="x", payload=p, index=i,
                     t=float(i), obd={k: obd.get(k) for k in al.OBD_SIGNALS},
                     times=obd.get("times", {}))


def driving_series(n: int = 20, src: str = "correlated_x.json") -> list[al.Sample]:
    """VSP e RPM variando; [3],[4] = VSP; [6,7]/8 = RPM; [50] = VSP (candidato)."""
    out = []
    for i in range(n):
        vsp = i * 3
        rpm = 700 + i * 90
        word = int(rpm * 8)
        tps = 10 + (i % 5) * 7
        p = payload(b3=vsp, b4=vsp, b6=word >> 8, b7=word & 0xFF, b50=vsp,
                    b9=200 - i, b30=55 + i, b19=tps)
        out.append(corr_sample(i, p, src, RPM=float(rpm), VSP=float(vsp),
                               TPS=float(tps), ECT=20.0 + i))
    return out


class TestHelpers(unittest.TestCase):
    def test_pearson_guards(self) -> None:
        self.assertIsNone(al.pearson([], []))
        self.assertIsNone(al.pearson([1.0], [2.0]))
        self.assertIsNone(al.pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]))
        self.assertIsNone(al.pearson([1.0, 2.0], [1.0]))
        self.assertAlmostEqual(al.pearson([1.0, 2.0, 3.0], [2.0, 4.0, 6.0]), 1.0)

    def test_percentile(self) -> None:
        self.assertIsNone(al.percentile([], 50))
        self.assertEqual(al.percentile([3.0, 1.0, 2.0], 50), 2.0)
        self.assertEqual(al.percentile(list(map(float, range(1, 101))), 95), 95.0)

    def test_fixture_base_is_valid(self) -> None:
        self.assertEqual(len(BASE), 69)
        self.assertEqual((BASE[0], BASE[68]), (0x01, 0x5F))


class TestIntegrity(unittest.TestCase):
    def test_counts_and_exceptions(self) -> None:
        good = al.Sample("a.json", "snapshot", "ok", BASE)
        bad_end = al.Sample("a.json", "snapshot", "end", payload(b68=0x00))
        bad_inv = al.Sample("a.json", "snapshot", "inv", payload(b9=100, b30=150))
        short = al.Sample("a.json", "snapshot", "short", BASE[:40])
        res = al.analyze_integrity([good, bad_end, bad_inv, short])
        self.assertEqual(res["tested"]["len69"], 4)
        self.assertEqual(res["ok"]["len69"], 3)
        self.assertEqual(res["tested"]["b68_end"], 3)       # o curto não é testado
        self.assertEqual(res["ok"]["b68_end"], 2)
        self.assertEqual(res["ok"]["b30_inv_b9"], 2)
        checks = {(e["label"], e["check"]) for e in res["exceptions"]}
        self.assertEqual(checks, {("end", "b68_end"), ("inv", "b30_inv_b9"),
                                  ("short", "len69")})

    def test_b30_tolerance_one(self) -> None:
        s = al.Sample("a", "snapshot", "x", payload(b9=100, b30=156))
        self.assertEqual(al.analyze_integrity([s])["exceptions"], [])


class TestConfirmed(unittest.TestCase):
    def test_good_correlation_has_no_regression(self) -> None:
        res = al.analyze_confirmed(driving_series())
        self.assertEqual(len(res["rows"]), 3)
        for r in res["rows"]:
            self.assertGreater(r["r"], 0.99)
            self.assertFalse(r["regression"])
        rpm = next(r for r in res["rows"] if r["field"] == "[6,7]/8")
        self.assertAlmostEqual(rpm["mean_diff"], 0.0, delta=0.2)

    def test_regression_flag(self) -> None:
        ss = driving_series()
        for i, s in enumerate(ss):            # [3] vira ruído sem relação com VSP
            s.payload = payload(s.payload, b3=(i * 37) % 23)
        rows = {r["field"]: r for r in al.analyze_confirmed(ss)["rows"]}
        self.assertTrue(rows["[3]"]["regression"])
        self.assertFalse(rows["[4]"]["regression"])

    def test_missing_obd(self) -> None:
        ss = [corr_sample(i, BASE, "correlated_old.json") for i in range(5)]
        res = al.analyze_confirmed(ss)
        self.assertEqual(res["rows"], [])
        self.assertEqual(res["no_obd"], ["correlated_old.json"])

    def test_constant_obd_is_indeterminate_not_regression(self) -> None:
        # OBD sem variação (carro parado): r é indefinido; isso NÃO é regressão.
        ss = [corr_sample(i, payload(b3=i), VSP=0.0, RPM=700.0) for i in range(5)]
        rows = al.analyze_confirmed(ss)["rows"]
        self.assertTrue(all(r["r"] is None for r in rows))
        self.assertTrue(all(r["indeterminate"] for r in rows))
        self.assertFalse(any(r["regression"] for r in rows))

    def test_lag_between_tcm_and_obd_is_compensated(self) -> None:
        # RPM real oscila (período 5 s); o TCM lê em T e o OBD 0,4 s depois.
        import math

        def f(t: float) -> float:
            return 2000 + 1500 * math.sin(2 * math.pi * t / 5.0)

        ss = []
        for i in range(40):
            t = 0.9 * i
            word = int(f(t) * 8)
            s = corr_sample(i, payload(b6=word >> 8, b7=word & 0xFF),
                            RPM=f(t + 0.4), VSP=0.0)
            s.times = {"tcm": t, "RPM": t + 0.4}
            ss.append(s)
        row = next(r for r in al.analyze_confirmed(ss)["rows"] if r["field"] == "[6,7]/8")
        self.assertLess(row["r"], 0.95)                 # bruto parece regressão
        self.assertGreater(row["r_comp"], 0.95)         # compensado, não é
        self.assertFalse(row["regression"])

    def test_no_timing_means_no_compensation(self) -> None:
        row = al.analyze_confirmed(driving_series())["rows"][0]
        self.assertIsNone(row["r_comp"])


class TestConfirmedReport(unittest.TestCase):
    def test_report_marks_constant_obd_as_indeterminate_not_regression(self) -> None:
        ss = [corr_sample(i, payload(b3=i), VSP=0.0, RPM=700.0) for i in range(5)]
        files = [al.FileResult(name="correlated_x.json", kind="correlated", samples=ss)]
        text = al.render_report(al.run_all(files, []), {})
        self.assertIn("indeterminado", text)
        self.assertNotIn("REGRESSÃO", text)


class TestTiming(unittest.TestCase):
    def test_old_capture_not_available(self) -> None:
        res = al.analyze_timing(driving_series(5))
        self.assertEqual(res["rows"], [{"source": "correlated_x.json", "available": False}])

    def test_new_capture_skew(self) -> None:
        ss = []
        for i in range(10):
            s = corr_sample(i, BASE, VSP=0.0)
            s.times = {"tcm": i + 0.1, "RPM": i + 0.2, "VSP": i + 0.1 + 0.05 * (i + 1)}
            ss.append(s)
        row = al.analyze_timing(ss)["rows"][0]
        self.assertTrue(row["available"])
        self.assertAlmostEqual(row["VSP"]["max"], 0.5)
        self.assertAlmostEqual(row["VSP"]["p50"], 0.25)
        self.assertAlmostEqual(row["RPM"]["p95"], 0.1)
        self.assertEqual(row["RPM"]["n"], 10)


class TestColdStart(unittest.TestCase):
    def test_series_and_correlations(self) -> None:
        row = al.analyze_cold_start(driving_series(20))["rows"][0]
        self.assertAlmostEqual(row["bytes"][9]["r_ect"], -1.0)
        self.assertAlmostEqual(row["bytes"][30]["r_ect"], 1.0)
        self.assertIsNone(row["bytes"][10]["r_ect"])          # [10] constante
        self.assertEqual((row["bytes"][9]["first"], row["bytes"][9]["last"]), (200, 181))
        self.assertEqual((row["ect_first"], row["ect_last"]), (20.0, 39.0))
        self.assertEqual(len(row["series"]), 12)

    def test_no_obd_no_rows(self) -> None:
        ss = [corr_sample(i, BASE) for i in range(3)]
        self.assertEqual(al.analyze_cold_start(ss)["rows"], [])


class TestSelector(unittest.TestCase):
    def test_label_parsing(self) -> None:
        cases = {"seletor_P_1": "P", "seletor_R_2": "R", "P_frio": "P", "D_rpm1000": "D",
                 "accel25_D": "D", "acel_em_P": "P", "R_parado": "R", "cruising_60": None,
                 "frio_manha": None, "tcc_80kmh": None, "": None}
        for lbl, exp in cases.items():
            self.assertEqual(al.selector_from_label(lbl), exp, lbl)
        self.assertEqual(al.selector_from_label("qualquer", "reverse"), "R")

    def test_fixture_selector_captures_match(self) -> None:
        ss = [al.Sample("ft.json", "field_test", f"seletor_{k}_1", CAPS[f"seletor_{k}"])
              for k in "PNDR"]
        res = al.analyze_selector(ss)
        self.assertEqual((res["match"], res["n"]), (4, 4))
        r = next(x for x in res["rows"] if x["selector"] == "R")
        self.assertEqual(r["b54"], {0x29: 1})
        self.assertEqual(r["range"], {(5, 5, 5): 1})

    def test_mismatch_and_unlabelled(self) -> None:
        ss = [al.Sample("ft.json", "field_test", "seletor_D_1", payload(b54=0x11)),
              al.Sample("ft.json", "field_test", "cruising_60", payload(b54=0x80))]
        res = al.analyze_selector(ss)
        self.assertEqual((res["match"], res["n"]), (0, 1))
        self.assertEqual(res["rows"][0]["nibbles"], {1: 1})


class TestLockupThrottle(unittest.TestCase):
    def test_bands_and_r(self) -> None:
        ss = driving_series(20)                     # VSP 0..57
        ss[-1].payload = payload(ss[-1].payload, b38=0x81)
        res = al.analyze_lockup_throttle(ss)
        self.assertEqual(res["bands"]["0"], {0xFE: 1})
        self.assertEqual(res["bands"]["51-80"], {0xFE: 2, 0x81: 1})    # 51, 54, 57 km/h
        row = res["rows"][0]
        self.assertAlmostEqual(row["b19_tps"], 1.0)
        self.assertEqual(row["b19_tps_n"], 20)
        self.assertIsNotNone(row["b19_rpm"])

    def test_missing_tps_guard(self) -> None:
        ss = [corr_sample(i, payload(b19=i), VSP=float(i)) for i in range(5)]
        row = al.analyze_lockup_throttle(ss)["rows"][0]
        self.assertIsNone(row["b19_tps"])
        self.assertEqual(row["b19_tps_n"], 0)


class TestByteScan(unittest.TestCase):
    def test_finds_candidate_and_skips_constant(self) -> None:
        res = al.analyze_byte_scan(driving_series(20))
        found = {(h["byte"], h["signal"]) for h in res["hits"]}
        self.assertIn((50, "VSP"), found)
        self.assertIn((3, "VSP"), found)
        self.assertNotIn(55, {h["byte"] for h in res["hits"]})   # constante
        self.assertAlmostEqual(abs(res["tail"][50]["r"]), 1.0)   # VSP e RPM lineares aqui
        self.assertNotIn(55, res["tail"])
        self.assertEqual(res["distinct"][55], 1)
        known = next(h for h in res["hits"] if h["byte"] == 3)
        self.assertIn("✅", known["known"])

    def test_min_n(self) -> None:
        self.assertEqual(al.analyze_byte_scan(driving_series(5))["hits"], [])


class TestFilesAndParsing(unittest.TestCase):
    def test_desde_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for n in ("correlated_20261024_100000.json", "correlated_20261106_080000.json",
                      "synthetic.csv"):
                (d / n).write_text("{}", encoding="utf-8")
            sel, skipped = al.select_files(d, "20261101_000000")
            self.assertEqual([p.name for p in sel], ["correlated_20261106_080000.json"])
            self.assertEqual(skipped[0][0], "synthetic.csv")
            sel_all, skipped_all = al.select_files(d, None)
            self.assertEqual(len(sel_all), 3)
            self.assertEqual(skipped_all, [])

    def test_choose_output_never_overwrites(self) -> None:
        import datetime as dt
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            existing = d / "x.md"
            existing.write_text("velho", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                al.choose_output(str(existing), d, dt.datetime.now())
            now = dt.datetime(2026, 11, 6, 8, 0, 0)
            (d / "analise_20261106_080000.md").write_text("velho", encoding="utf-8")
            self.assertEqual(al.choose_output(None, d, now).name, "analise_20261106_080000_1.md")

    def test_parse_kinds(self) -> None:
        h = BASE.hex()
        ft = al.parse_log("field_tests_1.json",
                          {"P_frio": {"hex": h, "decoded": {"b48_67_hex": "00"}}, "N": None},
                          "field_test")
        self.assertEqual([s.label for s in ft.samples], ["P_frio"])
        self.assertIn("1 cenário", ft.note)
        ft2 = al.parse_log("field_test_x.json",
                           {"scenario": "R", "label": "seletor_R_1", "hex": h}, "field_test")
        self.assertEqual(ft2.samples[0].label, "seletor_R_1")
        snap = al.parse_log("tcm_snapshot_a.json", {"label": "frio", "lids": {"0x1": h,
                            "0x2": "0200"}}, "snapshot")
        self.assertEqual(len(snap.samples), 1)
        other = al.parse_log("snapshot_tcm_x.json", {"module": "ecm", "lids": {"0x01": h}},
                             "snapshot")
        self.assertEqual(other.samples, [])
        rev = al.parse_log("reverse_state_a.json",
                           {"registros": [{"i": 0, "raw_hex": h}, {"i": 1, "raw_hex": None}]},
                           "reverse")
        self.assertEqual((rev.records, len(rev.samples)), (2, 1))
        self.assertEqual(rev.samples[0].kind, "reverse")


def _write_correlated(path: Path, new: bool) -> None:
    recs = []
    for s in driving_series(15):
        r = {"t": s.t, "i": s.index, "lid01_hex": s.payload.hex(), "lid01": {}}
        for k in al.OBD_SIGNALS:
            r[f"obd_{k}"] = s.obd[k] if new else None
        if new:
            r["t_tcm"] = s.t + 0.1
            for j, k in enumerate(al.OBD_SIGNALS):
                r[f"t_{k}"] = s.t + 0.2 + 0.05 * j
                r[f"obd_{k}_raw"] = "41"
        recs.append(r)
    recs.append({"t": 99.0, "i": 99, "lid01_hex": None})
    doc = {"label": path.stem, "records": recs}
    if new:
        doc["started_at"] = "2026-11-06T08:00:00-03:00"
    path.write_text(json.dumps(doc), encoding="utf-8")


class TestEndToEnd(unittest.TestCase):
    def test_main_writes_report_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            _write_correlated(d / "correlated_estrada_20261106_090000.json", new=True)
            _write_correlated(d / "correlated_old_20261024_095936.json", new=False)
            (d / "reverse_state_20261106_091000.json").write_text(json.dumps(
                {"registros": [{"i": 0, "raw_hex": CAPS["seletor_R"].hex()}]}), encoding="utf-8")
            (d / "roteiro_20261106_085000.txt").write_text("log", encoding="utf-8")
            out = d / "rel.md"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(al.main(["--logs", tmp, "--out", str(out)]), 0)
            text = out.read_text(encoding="utf-8")
            for i in range(1, 9):
                self.assertIn(f"## {i}.", text)
            self.assertIn("31 payloads", text)
            self.assertIn("não disponível (captura antiga, sem t_tcm)", text)
            self.assertIn("correlated_old_20261024_095936.json", text)
            self.assertIn("registro do roteiro", text)
            self.assertIn("Batem: 1/1", text)
            self.assertIn("✅ ok", text)
            with redirect_stderr(io.StringIO()):
                self.assertEqual(al.main(["--logs", tmp, "--out", str(out)]), 2)
            self.assertEqual(out.read_text(encoding="utf-8"), text)

            # --desde deixa só os arquivos novos
            out2 = d / "rel2.md"
            with redirect_stdout(io.StringIO()):
                al.main(["--logs", tmp, "--out", str(out2), "--desde", "20261106_000000"])
            text2 = out2.read_text(encoding="utf-8")
            self.assertIn("16 payloads", text2)
            self.assertNotIn("correlated_old", text2)

    def test_default_output_in_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_correlated(Path(tmp) / "correlated_a_20261106_090000.json", new=True)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(al.main(["--logs", tmp]), 0)
            self.assertEqual(len(list(Path(tmp).glob("analise_*.md"))), 1)

    def test_bad_desde(self) -> None:
        with redirect_stderr(io.StringIO()):
            self.assertEqual(al.main(["--desde", "2026-11-06"]), 2)


if __name__ == "__main__":
    unittest.main()
