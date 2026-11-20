"""Roteiro guiado do carro — comandos válidos e execução, sem hardware."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

import roteiro_carro  # noqa: E402
from openscan_obd.cli import main as cli_main  # noqa: E402

CAR_SESSION_CHOICES = set(
    re.search(r'choices=\[([^\]]+)\]', (ROOT / "car_session.py").read_text(encoding="utf-8"))
    .group(1).replace('"', "").replace(" ", "").split(",")
)


class TestEtapas(unittest.TestCase):
    def setUp(self) -> None:
        self.etapas = roteiro_carro.montar_etapas(roteiro_carro.DEFAULT_DLL)

    def test_every_cli_command_parses(self) -> None:
        for etapa in self.etapas:
            for modelo in etapa.comandos:
                cmd = roteiro_carro.preparar(modelo)
                if cmd[:2] != ["-m", "openscan_obd.cli"]:
                    continue
                name, *args = cmd[2:]
                with self.subTest(etapa=etapa.titulo, comando=name):
                    self.assertIn(name, cli_main.commands)
                    cli_main.commands[name].make_context(name, list(args))

    def test_every_car_session_command_exists(self) -> None:
        for etapa in self.etapas:
            for cmd in etapa.comandos:
                if not cmd[0].endswith("car_session.py"):
                    continue
                with self.subTest(etapa=etapa.titulo, comando=cmd[1]):
                    self.assertIn(cmd[1], CAR_SESSION_CHOICES)
                    flags = {a for a in cmd[2:] if a.startswith("--")}
                    self.assertLessEqual(flags, {"--dll", "--duration", "--label"})

    def test_saved_output_names_match_commands(self) -> None:
        for etapa in self.etapas:
            if etapa.salvar_saida_como is not None:
                self.assertEqual(len(etapa.salvar_saida_como), len(etapa.comandos))

    def test_first_step_is_adapter_check(self) -> None:
        primeira = self.etapas[0]
        self.assertEqual(primeira.comandos, [roteiro_carro.cli(
            "j2534-check", "--dll", roteiro_carro.DEFAULT_DLL)])
        self.assertIn("não precisa estar no carro", primeira.condicao)

    def test_kwp_dtc_step_runs_both_request_formats(self) -> None:
        etapa = next(e for e in self.etapas if "KWP" in e.titulo)
        self.assertEqual(etapa.salvar_saida_como, [
            "kwp_dtc_ecm", "kwp_dtc_ecm_grupo", "kwp_dtc_tcm", "kwp_dtc_tcm_grupo"])
        for cmd, nome in zip(etapa.comandos, etapa.salvar_saida_como):
            with self.subTest(nome=nome):
                self.assertEqual(cmd[cmd.index("--txid") + 1],
                                 "7E0" if "ecm" in nome else "7E1")
                self.assertEqual("--group" in cmd, nome.endswith("_grupo"))
                if "--group" in cmd:
                    self.assertEqual(cmd[cmd.index("--group") + 1], "FF00")

    def test_non_interactive_steps_save_their_screen_output(self) -> None:
        # A15: scan/ecm/discover/outros módulos só imprimiam no console e não
        # deixavam log. Etapas sem pedir_antes e sem arquivo próprio devem salvar.
        own_file = {"snapshot", "read-kwp-dtcs", "capture", "gateway", "correlated"}
        interactive = {"reverse", "gateway"}      # pedem ENTER: não dá para capturar
        for etapa in self.etapas:
            if etapa.pedir_antes or etapa.para_sozinho_em_s:
                continue
            nomes = []
            for modelo in etapa.comandos:
                cmd = roteiro_carro.preparar(modelo)
                nomes.append(cmd[2] if cmd[:2] == ["-m", "openscan_obd.cli"] else cmd[1:2])
            flat = {n if isinstance(n, str) else (n[0] if n else "") for n in nomes}
            if flat & (own_file | interactive):
                continue
            with self.subTest(etapa=etapa.titulo):
                self.assertIsNotNone(etapa.salvar_saida_como)
                self.assertEqual(len(etapa.salvar_saida_como), len(etapa.comandos))

    def test_only_read_operations(self) -> None:
        forbidden = {"clear", "write", "reset", "0x14", "0x2E", "0x31", "0x27"}
        for etapa in self.etapas:
            for cmd in etapa.comandos:
                self.assertFalse(forbidden & {c.lower() for c in cmd}, cmd)

    def test_capture_name_is_fresh_each_run(self) -> None:
        dash = next(e for e in self.etapas if e.para_sozinho_em_s)
        cmd = roteiro_carro.preparar(dash.comandos[0])
        capture = cmd[cmd.index("--capture") + 1]
        self.assertNotIn("{agora}", capture)
        self.assertRegex(capture, r"gateway_ecm_\d{8}_\d{6}\.jsonl$")


class TestExecucao(unittest.TestCase):
    def test_listar_runs_nothing(self) -> None:
        self.assertEqual(roteiro_carro.main(["--listar"]), 0)

    def test_command_return_code(self) -> None:
        self.assertEqual(roteiro_carro.rodar_comando(["-c", "pass"], None), "saiu com código 0")

    def test_skipped_steps_come_back_at_the_end(self) -> None:
        import tempfile
        from unittest.mock import patch

        etapas = roteiro_carro.montar_etapas(roteiro_carro.DEFAULT_DLL)
        total = len(etapas)

        def feita(i: int) -> list[str]:
            # "pronto" para cada pedido antes de comando (ex.: alavanca P/N/D/R)
            pedidos = etapas[i - 1].pedir_antes or []
            return ["fazer", *(["pronto"] * len(pedidos)), "seguir"]

        # 1ª passada: pula 3 e 4, faz o resto.
        keys = []
        for i in range(1, total + 1):
            keys += ["pular"] if i in (3, 4) else feita(i)
        # final: volta às puladas; faz a 3, pula a 4; depois encerra.
        keys += ["voltar", *feita(3), "pular", "terminar"]
        teclas = iter(keys)
        ran = []

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(roteiro_carro, "LOGS", Path(tmp)), \
                patch.object(roteiro_carro, "verificar_ambiente", lambda _dll: []), \
                patch.object(roteiro_carro, "esperar_tecla", lambda *_a: next(teclas)), \
                patch.object(roteiro_carro, "rodar_comando",
                             lambda cmd, _t: ran.append(cmd) or "ok"), \
                patch.object(roteiro_carro, "rodar_e_salvar",
                             lambda cmd, _n: ran.append(cmd) or "ok"):
            self.assertEqual(roteiro_carro.main([]), 0)
            log = next(Path(tmp).glob("roteiro_*.txt")).read_text(encoding="utf-8")

        self.assertRaises(StopIteration, next, teclas)
        self.assertIn("voltando às puladas: [3, 4]", log)
        self.assertIn("não feitas [4]", log)
        self.assertIn("etapa 3 INÍCIO", log)
        self.assertNotIn("etapa 4 INÍCIO", log)

    def test_selector_step_asks_before_each_reading_and_can_skip_one(self) -> None:
        import tempfile
        from unittest.mock import patch

        etapas = roteiro_carro.montar_etapas(roteiro_carro.DEFAULT_DLL)
        n = next(i for i, e in enumerate(etapas, 1) if e.pedir_antes)
        seletor = etapas[n - 1]
        self.assertEqual(len(seletor.pedir_antes), len(seletor.comandos))
        self.assertIn("alavanca em P", seletor.pedir_antes[0])
        for cmd in seletor.comandos:
            self.assertEqual(cmd[2], "snapshot")
            self.assertIn("seletor_", cmd[cmd.index("--label") + 1])

        # Faz só a etapa do seletor: pula a 2ª leitura (N), faz as outras 7.
        keys = ["fazer", "pronto", "pular", *(["pronto"] * 6), "seguir"]
        teclas = iter(keys)
        ran = []
        with tempfile.TemporaryDirectory() as tmp,                 patch.object(roteiro_carro, "LOGS", Path(tmp)),                 patch.object(roteiro_carro, "verificar_ambiente", lambda _dll: []),                 patch.object(roteiro_carro, "esperar_tecla", lambda *_a: next(teclas)),                 patch.object(roteiro_carro, "montar_etapas", lambda _dll: [seletor]),                 patch.object(roteiro_carro, "rodar_comando",
                             lambda cmd, _t: ran.append(cmd) or "ok"):
            self.assertEqual(roteiro_carro.main([]), 0)
            log = next(Path(tmp).glob("roteiro_*.txt")).read_text(encoding="utf-8")
        self.assertEqual(len(ran), 7)
        self.assertIn("leitura 2 PULADA: Coloque a alavanca em N", log)

    def test_keep_awake_sets_and_restores_execution_state(self) -> None:
        calls = []

        class FakeKernel32:
            def SetThreadExecutionState(self, flags):  # noqa: N802 — nome da API
                calls.append(flags)
                return 0x80000000

        with roteiro_carro.manter_acordado(FakeKernel32()) as ativo:
            self.assertTrue(ativo)
            self.assertEqual(len(calls), 1)
        expected = (roteiro_carro.ES_CONTINUOUS | roteiro_carro.ES_SYSTEM_REQUIRED
                    | roteiro_carro.ES_DISPLAY_REQUIRED)
        self.assertEqual(calls, [expected, roteiro_carro.ES_CONTINUOUS])

    def test_keep_awake_failure_does_not_stop_the_script(self) -> None:
        class BrokenKernel32:
            def SetThreadExecutionState(self, flags):  # noqa: N802
                raise OSError("sem permissão")

        with roteiro_carro.manter_acordado(BrokenKernel32()) as ativo:
            self.assertFalse(ativo)

    def test_timed_command_is_stopped(self) -> None:
        result = roteiro_carro.rodar_comando(["-c", "import time; time.sleep(30)"], 1)
        self.assertIn("parado", result)


if __name__ == "__main__":
    unittest.main()


class TestRoteiroProximo(unittest.TestCase):
    """Roteiro do próximo teste: só o que falta validar no carro (SDD 2026-11-15)."""

    def setUp(self) -> None:
        self.etapas = roteiro_carro.montar_etapas_proximo(roteiro_carro.DEFAULT_DLL)

    def _nomes(self, etapa) -> list[str]:
        return [roteiro_carro.preparar(c)[2] for c in etapa.comandos
                if roteiro_carro.preparar(c)[:2] == ["-m", "openscan_obd.cli"]]

    def test_every_command_parses(self) -> None:
        for etapa in self.etapas:
            for modelo in etapa.comandos:
                cmd = roteiro_carro.preparar(modelo)
                if cmd[0].endswith("car_session.py"):      # coberto por test_every_car_session_command_exists
                    continue
                name, *args = cmd[2:]
                with self.subTest(etapa=etapa.titulo, comando=name):
                    self.assertEqual(cmd[:2], ["-m", "openscan_obd.cli"])
                    self.assertIn(name, cli_main.commands)
                    cli_main.commands[name].make_context(name, list(args))

    def test_first_is_adapter_check_and_last_is_road_test(self) -> None:
        self.assertEqual(self._nomes(self.etapas[0]), ["j2534-check"])
        ultima = self.etapas[-1]
        self.assertIn("movimento", ultima.condicao)
        self.assertEqual(self._nomes(ultima), ["dashboard"])
        self.assertIn("--capture", ultima.comandos[0])

    def test_dashboard_steps_capture_with_fresh_names_and_stop_alone(self) -> None:
        dashes = [e for e in self.etapas if "dashboard" in self._nomes(e)]
        self.assertGreaterEqual(len(dashes), 4)
        vistos = set()
        for e in dashes:
            with self.subTest(etapa=e.titulo):
                self.assertTrue(e.para_sozinho_em_s)
                cmd = roteiro_carro.preparar(e.comandos[0])
                self.assertIn("--hardware", cmd)
                cap = cmd[cmd.index("--capture") + 1]
                self.assertNotIn("{agora}", cap)
                vistos.add(cap.split("_{agora}")[0])
        self.assertEqual(len(vistos), len(dashes))       # cada etapa tem prefixo próprio

    def test_probe_dtc_steps_run_in_order_h1_h3_before_a3(self) -> None:
        idx = [i for i, e in enumerate(self.etapas) if "probe-dtc" in self._nomes(e)]
        self.assertEqual(len(idx), 2)
        sem_a3, com_a3 = (self.etapas[i] for i in idx)
        self.assertNotIn("--allow-a3", sem_a3.comandos[0])
        self.assertIn("--allow-a3", com_a3.comandos[0])

    def test_a3_step_needs_explicit_parked_confirmation_before_running(self) -> None:
        a3 = next(e for e in self.etapas if "--allow-a3" in e.comandos[0])
        self.assertIn("--confirm-parked", a3.comandos[0])
        self.assertTrue(a3.pedir_antes)
        pedido = " ".join(a3.pedir_antes).lower()
        for palavra in ("p", "freio de mão", "motor"):
            self.assertIn(palavra, pedido)
        self.assertEqual(len(a3.pedir_antes), len(a3.comandos))
        # nenhum outro passo pode carregar a flag
        outros = [e for e in self.etapas if e is not a3]
        for e in outros:
            for c in e.comandos:
                self.assertNotIn("--allow-a3", c)

    def test_full_ecm_lid_sweep_step_hunts_injector_pulse_read_only(self) -> None:
        etapa = next(e for e in self.etapas if "ecm_sweep_full" in e.comandos[0])
        self.assertIn("ecm_sweep_full", CAR_SESSION_CHOICES)
        self.assertEqual(etapa.salvar_saida_como, ["ecm_sweep_full"])
        self.assertIn("pulso de injeção", " ".join(etapa.instrucoes).lower())

    def test_every_car_session_command_exists(self) -> None:
        for etapa in self.etapas:
            for cmd in etapa.comandos:
                if not cmd[0].endswith("car_session.py"):
                    continue
                with self.subTest(etapa=etapa.titulo, comando=cmd[1]):
                    self.assertIn(cmd[1], CAR_SESSION_CHOICES)
                    self.assertLessEqual({a for a in cmd[2:] if a.startswith("--")},
                                         {"--dll", "--duration", "--label"})

    def test_only_read_operations(self) -> None:
        forbidden = {"clear", "write", "reset", "0x14", "0x2e", "0x31", "0x27"}
        for e in self.etapas:
            for c in e.comandos:
                self.assertFalse(forbidden & {x.lower() for x in c}, c)

    def test_console_steps_save_their_output(self) -> None:
        for e in self.etapas:
            if e.para_sozinho_em_s or e.pedir_antes and "--allow-a3" not in e.comandos[0]:
                continue
            with self.subTest(etapa=e.titulo):
                self.assertIsNotNone(e.salvar_saida_como)
                self.assertEqual(len(e.salvar_saida_como), len(e.comandos))

    def test_selecting_the_roteiro_from_the_command_line(self) -> None:
        self.assertEqual(roteiro_carro.main(["--roteiro", "proximo", "--listar"]), 0)
        with self.assertRaises(SystemExit):
            roteiro_carro.main(["--roteiro", "inexistente", "--listar"])

    def test_launcher_exists_and_passes_the_option(self) -> None:
        bat = (ROOT / "roteiro_proximo.bat").read_text(encoding="utf-8")
        self.assertIn("--roteiro proximo", bat)
        self.assertIn(".venv\\Scripts\\python.exe", bat)


class TestRoteiroEstrada(unittest.TestCase):
    def test_estrada_checks_adapter_then_captures_dashboard_while_driving(self) -> None:
        etapas = roteiro_carro.montar_etapas_estrada(roteiro_carro.DEFAULT_DLL)
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in etapas],
                         ["j2534-check", "dashboard"])
        dash = etapas[1]
        self.assertIn("nissan-sentra-b16-2010", dash.comandos[0])
        self.assertTrue(dash.para_sozinho_em_s and dash.para_sozinho_em_s >= 1200)
        self.assertTrue(any("NÃO" in t or "quem dirige" in t for t in [dash.condicao, *dash.instrucoes]))
        for e in etapas:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        self.assertIn("estrada", roteiro_carro.ROTEIROS)


class TestRoteiroColeta(unittest.TestCase):
    def test_coleta_discovers_then_records_then_sniffs_and_commands_parse(self) -> None:
        etapas = roteiro_carro.montar_etapas_coleta(roteiro_carro.DEFAULT_DLL, "gasolina")
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in etapas],
                         ["j2534-check", "collect-discover", "collect", "sniff"])
        self.assertIn("gasolina", etapas[2].comandos[0])
        self.assertTrue(etapas[2].para_sozinho_em_s >= 15 * 60)
        for e in etapas:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        self.assertIn("coleta", roteiro_carro.ROTEIROS)
        bat = (Path(roteiro_carro.__file__).parent / "roteiro_coleta.bat").read_text()
        self.assertIn("--roteiro coleta", bat)


class TestRoteiroDescobertaGravacao(unittest.TestCase):
    def test_split_roteiros_and_bats(self) -> None:
        d = roteiro_carro.montar_etapas_descoberta(roteiro_carro.DEFAULT_DLL)
        g = roteiro_carro.montar_etapas_gravacao(roteiro_carro.DEFAULT_DLL, "gasolina")
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in d], ["j2534-check", "collect-discover"])
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in g], ["j2534-check", "collect", "sniff"])
        self.assertIn("1100-12FF", d[1].comandos[0])
        dd = roteiro_carro.montar_etapas_dids(roteiro_carro.DEFAULT_DLL)
        self.assertIn("todos", dd[1].comandos[0])
        for e in dd:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        root = Path(roteiro_carro.__file__).parent
        for nome in ("descoberta", "gravacao", "dids"):
            self.assertIn(f"--roteiro {nome}", (root / f"roteiro_{nome}.bat").read_text())


class TestRoteiroGuiado(unittest.TestCase):
    def test_guiado_roda_coleta_e_escuta_com_estimulos_e_parse_ok(self) -> None:
        g = roteiro_carro.montar_etapas_guiado(roteiro_carro.DEFAULT_DLL, "gasolina")
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in g], ["j2534-check", "collect", "sniff"])
        for e in g[1:]:
            self.assertIn("--estimulos", e.comandos[0])
            self.assertIn("parado", e.comandos[0])
            self.assertIn("gasolina", e.comandos[0])
            self.assertTrue(e.para_sozinho_em_s and e.para_sozinho_em_s > 310)
        for e in g:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        root = Path(roteiro_carro.__file__).parent
        self.assertIn("--roteiro guiado", (root / "roteiro_guiado.bat").read_text())

    def test_guiado_andando(self) -> None:
        g = roteiro_carro.montar_etapas_guiado_andando(roteiro_carro.DEFAULT_DLL, "gasolina")
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in g],
                         ["j2534-check", "ler-erros", "collect", "collect", "sniff", "collect", "ler-erros"])
        self.assertIn("antes", g[1].comandos[0])
        self.assertIn("depois", g[6].comandos[0])
        self.assertIn("dashboard", " ".join(g[0].instrucoes).lower())
        self.assertIn("SEM DESLIGAR", g[6].condicao)
        self.assertIn("--minutes", g[2].comandos[0])
        for e in g[3:5]:
            self.assertIn("andando", e.comandos[0])
        puxada = g[5].comandos[0]
        self.assertIn("puxada", puxada)
        self.assertIn("--so-obd", puxada)
        self.assertIn("--pids", puxada)
        self.assertIn("local seguro", g[5].condicao.lower())
        for e in g:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        root = Path(roteiro_carro.__file__).parent
        self.assertIn("--roteiro guiado_andando", (root / "roteiro_guiado_andando.bat").read_text())


class TestRoteiroPendentes(unittest.TestCase):
    def test_pendentes_runs_scan_22_on_tcm_then_dashboard_and_commands_parse(self) -> None:
        etapas = roteiro_carro.montar_etapas_pendentes(roteiro_carro.DEFAULT_DLL)
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in etapas],
                         ["j2534-check", "scan-22", "dashboard"])
        for e in etapas:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        scan = etapas[1]
        self.assertIn("7E1", scan.comandos[0])
        self.assertFalse(scan.salvar_saida_como)      # progresso ao vivo
        self.assertIn("nissan-sentra-b16-2010", etapas[2].comandos[0])
        self.assertIn("pendentes", roteiro_carro.ROTEIROS)


class TestRoteiroVarredura(unittest.TestCase):
    def test_varredura_has_adapter_check_then_scan_all_and_commands_parse(self) -> None:
        etapas = roteiro_carro.montar_etapas_varredura(roteiro_carro.DEFAULT_DLL)
        self.assertEqual([roteiro_carro.preparar(e.comandos[0])[2] for e in etapas],
                         ["j2534-check", "scan-all"])
        for e in etapas:
            name, *args = roteiro_carro.preparar(e.comandos[0])[2:]
            cli_main.commands[name].make_context(name, list(args))
        self.assertIn("varredura", roteiro_carro.ROTEIROS)

    def test_scan_all_streams_progress_instead_of_capturing_output(self) -> None:
        # Capturar a saída (salvar_saida_como) esconde o progresso até o fim: o usuário via tela parada.
        scan = roteiro_carro.montar_etapas_varredura(roteiro_carro.DEFAULT_DLL)[1]
        self.assertFalse(scan.salvar_saida_como)


class TestRoteiroErros:
    def test_so_le_e_nao_apaga(self):
        from roteiro_carro import montar_etapas_erros
        etapas = montar_etapas_erros("x.dll")
        cmds = [" ".join(c) for e in etapas for c in e.comandos]
        assert any("ler-erros" in c for c in cmds)
        assert not any(t in c.split() for c in cmds for t in ("04", "14", "clear"))
