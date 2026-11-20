"""analisar-log: relatório de calibração (combustível, avanço, MAF, malha, puxadas) a partir de coleta_*.jsonl."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from openscan_obd import analise_tuning as at
from openscan_obd.cli import main


def pid(t: float, p: int, *data: int, src: str | None = None) -> dict:
    return {"t": t, "src": src or f"obd:{p:02X}", "raw": bytes([0x41, p, *data]).hex(), "ms": 20}


def ciclo(t: float, rpm: float, speed: int, load: float, thr: float, stft: float = 0, ltft: float = 20,
          maf: float = 10, timing: float = 15, status: int = 2) -> list[dict]:
    r4 = int(rpm * 4)
    m = int(maf * 100)
    return [
        pid(t, 0x0C, r4 >> 8, r4 & 0xFF), pid(t, 0x0D, speed), pid(t, 0x04, int(load * 255 / 100)),
        pid(t, 0x11, int(thr * 255 / 100)), pid(t, 0x06, int(128 + stft * 128 / 100)),
        pid(t, 0x07, int(128 + ltft * 128 / 100)), pid(t, 0x10, m >> 8, m & 0xFF),
        pid(t, 0x0E, int((timing + 64) * 2)), pid(t, 0x03, status, 0),
        pid(t, 0x05, 127), pid(t, 0x0F, 70), pid(t, 0x44, 0x80, 0x00), pid(t, 0x14, 90, 0xFF),
        pid(t, 0x42, 0x38, 0x00),
    ]


def log(path: Path, ciclos: list[list[dict]], extra: list[dict] | None = None) -> Path:
    rows = [{"event": "coleta_started", "t": 0}] + [r for c in ciclos for r in c] + (extra or [])
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


class TestDecodificacao(unittest.TestCase):
    def test_amostra_decodifica_formulas_j1979(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = log(Path(d) / "coleta_a.jsonl", [ciclo(1.0, 2000, 60, 40, 20, stft=5, ltft=-10, maf=12.5, timing=20)])
            [a] = at.amostras(at.carregar_obd([p]))
        self.assertAlmostEqual(a["rpm"], 2000, delta=1)
        self.assertEqual(a["speed"], 60)
        self.assertAlmostEqual(a["load"], 40, delta=0.5)
        self.assertAlmostEqual(a["stft"], 5, delta=1)
        self.assertAlmostEqual(a["ltft"], -10, delta=1)
        self.assertAlmostEqual(a["maf"], 12.5, delta=0.02)
        self.assertAlmostEqual(a["timing"], 20, delta=0.5)
        self.assertEqual(a["ect"], 87)
        self.assertEqual(a["fuel_status"], 2)

    def test_modos_de_dtc_com_o_nome_antigo_nao_viram_pid(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ruido = [{"t": 0.5, "src": "obd:07", "raw": "4700", "ms": 5}, {"t": 0.5, "src": "obd:03", "raw": "4300", "ms": 5}]
            p = log(Path(d) / "coleta_a.jsonl", [ciclo(1.0, 800, 0, 20, 12)], extra=ruido)
            serie = at.carregar_obd([p])
        self.assertEqual(len(serie[0x07]), 1)
        self.assertEqual(len(serie[0x03]), 1)

    def test_nrc_e_timeout_sao_ignorados(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = log(Path(d) / "coleta_a.jsonl", [ciclo(1.0, 800, 0, 20, 12)],
                    extra=[{"t": 2, "src": "obd:0C", "nrc": "12", "ms": 5}, {"t": 2, "src": "obd:0D", "status": "timeout"}])
            self.assertEqual(len(at.carregar_obd([p])[0x0C]), 1)


class TestRelatorio(unittest.TestCase):
    def _amostras(self, ciclos):
        with tempfile.TemporaryDirectory() as d:
            return at.amostras(at.carregar_obd([log(Path(d) / "coleta_a.jsonl", ciclos)]))

    def test_mapa_agrupa_por_rpm_e_carga_e_exige_minimo_de_amostras(self) -> None:
        cs = [ciclo(i, 2100, 50, 45, 25, stft=4, ltft=10) for i in range(4)] + [ciclo(10, 800, 0, 18, 12, stft=-2, ltft=10)]
        m = at.mapa(self._amostras(cs), "trim", rpm_step=500, carga_step=20, min_n=3)
        self.assertEqual(len(m["celulas"]), 1)
        (k, v), = m["celulas"].items()
        self.assertEqual(k, (2000, 40))
        self.assertAlmostEqual(v["media"], 14, delta=1.5)
        self.assertEqual(v["n"], 4)

    def test_puxada_so_conta_com_acelerador_alto_por_varias_amostras(self) -> None:
        cs = [ciclo(i, 2000 + 400 * i, 20 + 12 * i, 80, 85) for i in range(5)] + [ciclo(20, 900, 30, 20, 15)]
        p = at.puxadas(self._amostras(cs), thr_min=70, min_amostras=3)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0]["n"], 5)
        self.assertGreater(p[0]["rpm_max"], p[0]["rpm_min"])
        self.assertAlmostEqual(p[0]["duracao_s"], 4, delta=0.1)

    def test_tempo_de_aceleracao_entre_velocidades(self) -> None:
        cs = [ciclo(i, 2500, 20 + 10 * i, 60, 50) for i in range(8)]       # 20..90 km/h, 1 s por passo
        r = at.tempo_aceleracao(self._amostras(cs), 30, 60)
        self.assertAlmostEqual(r, 3.0, delta=0.1)
        self.assertIsNone(at.tempo_aceleracao(self._amostras(cs), 30, 200))

    def test_relatorio_avisa_quando_nao_ha_puxada_nem_sonda_larga(self) -> None:
        cs = [ciclo(i, 1500, 40, 30, 20) for i in range(6)]
        txt = at.relatorio(self._amostras(cs), arquivos=["coleta_a.jsonl"])
        self.assertIn("Sem puxada", txt)
        self.assertIn("20%", txt)                       # acelerador máximo registrado
        self.assertIn("banda larga", txt.lower())
        self.assertIn("LTFT", txt)
        self.assertIn("malha fechada", txt.lower())

    def test_observacoes_sobre_ltft_alto_e_lambda_saturado(self) -> None:
        cs = [ciclo(i, 1500, 40, 30, 20, ltft=20) for i in range(6)]
        for r in cs[0]:
            if r["src"] == "obd:44":
                r["raw"] = "41 44 ff ff".replace(" ", "")
        txt = at.relatorio(self._amostras(cs), arquivos=["coleta_a.jsonl"])
        self.assertIn("LTFT médio alto", txt)
        self.assertIn("gasolina", txt)
        self.assertIn("saturada", txt)

    def test_sem_trecho_para_tempo_de_aceleracao_diz_isso(self) -> None:
        cs = [ciclo(i, 1500, 40, 30, 20) for i in range(6)]
        self.assertIn("Sem trecho contínuo", at.relatorio(self._amostras(cs), arquivos=["a"]))

    def test_relatorio_vazio_nao_quebra(self) -> None:
        self.assertIn("Sem amostras", at.relatorio([], arquivos=[]))


class TestCli(unittest.TestCase):
    def test_comando_gera_markdown_na_pasta_de_saida(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            log(Path(d) / "coleta_20261119_000000.jsonl", [ciclo(i, 1500 + 50 * i, 40, 30, 20) for i in range(6)])
            res = CliRunner().invoke(main, ["analisar-log", "--out-dir", d])
            self.assertEqual(res.exit_code, 0, res.output)
            saidas = list(Path(d).glob("analise_*.md"))
            self.assertEqual(len(saidas), 1)
            self.assertIn("LTFT", saidas[0].read_text(encoding="utf-8"))

    def test_cria_a_pasta_de_saida_se_nao_existir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            arq = log(Path(d) / "coleta_x.jsonl", [ciclo(i, 1500, 40, 30, 20) for i in range(4)])
            saida = Path(d) / "nova" / "pasta"
            res = CliRunner().invoke(main, ["analisar-log", "-a", str(arq), "--out-dir", str(saida)])
            self.assertEqual(res.exit_code, 0, res.output)
            self.assertEqual(len(list(saida.glob("analise_*.md"))), 1)

    def test_sem_log_da_erro_claro(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            res = CliRunner().invoke(main, ["analisar-log", "--out-dir", d])
            self.assertNotEqual(res.exit_code, 0)
            self.assertIn("coleta", res.output)


class TestSecoesExtras(unittest.TestCase):
    def test_overdrive_compara_rpm_por_kmh(self):
        from openscan_obd import analise_tuning as at
        am = [{"t": float(i), "rpm": 1500.0, "speed": 70.0} for i in range(5)] + \
             [{"t": 10.0 + i, "rpm": 3400.0, "speed": 70.0} for i in range(5)]
        od = [(float(i), 0) for i in range(5)] + [(10.0 + i, 1) for i in range(5)]
        txt = "\n".join(at.secao_overdrive(am, od))
        self.assertIn("O/D OFF gira 2.3x mais", txt)

    def test_overdrive_sem_lid(self):
        from openscan_obd import analise_tuning as at
        self.assertIn("Sem leitura", "\n".join(at.secao_overdrive([], [])))

    def test_temperatura_contagem(self):
        from openscan_obd import analise_tuning as at
        serie = [(float(i) * 10, 75 + i * 5) for i in range(10)]
        txt = "\n".join(at.secao_temperatura_fluido(serie))
        self.assertIn("75 no início, 120 no fim", txt)
        self.assertIn("36 °C no início", txt)
        self.assertIn("ESTIMADA", txt)

    def test_erros_novos_codigos(self):
        import json
        import tempfile
        from pathlib import Path
        from openscan_obd import analise_tuning as at
        def mk(d, nome, codes):
            p = Path(d) / nome
            p.write_text(json.dumps({"modulos": [{"modulo": "TCM", "decodificado": {"codes": [{"code": c} for c in codes]}}]}))
            return p
        with tempfile.TemporaryDirectory() as d:
            a = mk(d, "erros_antes_1.json", ["P1722"])
            b = mk(d, "erros_depois_2.json", ["P1722", "P0746"])
            txt = "\n".join(at.secao_erros([a, b]))
        self.assertIn("TCM: P0746", txt)
        self.assertIn("erros_antes_1.json: P1722", txt)


class TestPartidaAFrio(unittest.TestCase):
    def _log(self, d, nome, ect, iat, contagem):
        import json
        from pathlib import Path
        p = Path(d) / nome
        L = [{"t": 1.0, "src": "obd:05", "raw": f"4105{ect + 40:02x}"},
             {"t": 1.0, "src": "obd:0F", "raw": f"410f{iat + 40:02x}"},
             {"t": 1.1, "src": "kwp:tcm_cvt:01", "raw": "6101" + "00" * 29 + f"{contagem:02x}" + "00" * 40}]
        p.write_text("\n".join(json.dumps(x) for x in L), encoding="utf-8")
        return p

    def test_frio_compativel_e_nao_frio(self):
        import tempfile
        from openscan_obd import analise_tuning as at
        with tempfile.TemporaryDirectory() as d:
            ok = self._log(d, "frio.jsonl", 26, 25, 55)     # contagem 55 ~ 24 °C pela tabela
            quente = self._log(d, "quente.jsonl", 63, 33, 75)
            txt = "\n".join(at.secao_partida_a_frio([ok, quente]))
        self.assertIn("compatível com a tabela", txt)
        self.assertIn("NÃO estava frio", txt)

    def test_sem_arquivos_validos(self):
        from openscan_obd import analise_tuning as at
        self.assertIn("Nenhuma partida a frio", "\n".join(at.secao_partida_a_frio([])))
