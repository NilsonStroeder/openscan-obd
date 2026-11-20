import threading

import pytest

from openscan_obd.gateway import estimulos as est


def test_sequencia_parado_bem_formada():
    ids = [s.id for s in est.PARADO]
    assert len(ids) == len(set(ids)) >= 20
    for s in est.PARADO:
        assert s.texto.strip() and s.duracao_s >= 3
    assert 240 <= est.duracao_total(est.PARADO) <= 720


def test_sequencia_parado_so_tem_acoes_seguras():
    # nada que exija carro andando; câmbio sempre com pé no freio
    for s in est.PARADO:
        if s.id.startswith("cambio_"):
            assert "freio" in s.texto.lower()
    assert est.PARADO[0].id == "repouso"


def test_run_estimulos_marca_inicio_e_fim_em_ordem():
    passos = [est.Estimulo("a", "Faça A", 5), est.Estimulo("b", "Faça B", 4)]
    marcas, falas, relogio, dormiu = [], [], [100.0], []

    def dorme(s):
        dormiu.append(s)
        relogio[0] += s

    est.run_estimulos(passos, marcas.append, say=falas.append, beep=lambda: None,
                      sleep=dorme, wall=lambda: relogio[0])
    assert [(m["event"], m.get("id")) for m in marcas] == [
        ("estimulos_started", None), ("estimulo", "a"), ("estimulo", "b"), ("estimulos_finished", None)]
    assert marcas[1]["t"] == 100.0 and marcas[2]["t"] == 105.0
    assert marcas[1]["texto"] == "Faça A" and marcas[1]["dur_s"] == 5
    assert marcas[-1]["completos"] is True
    assert sum(dormiu) == pytest.approx(9)
    assert any("Faça A" in f for f in falas) and any("Faça B" in f for f in falas)


def test_run_estimulos_para_quando_pedido():
    parar = threading.Event()
    passos = [est.Estimulo("a", "A", 5), est.Estimulo("b", "B", 5)]
    marcas = []

    def dorme(s):
        parar.set()

    est.run_estimulos(passos, marcas.append, say=lambda m: None, beep=lambda: None,
                      sleep=dorme, wall=lambda: 1.0, parar=parar)
    assert [m.get("id") for m in marcas if m["event"] == "estimulo"] == ["a"]
    assert marcas[-1]["completos"] is False


def test_cadencia_total_le_todos_os_modulos_a_cada_ciclo():
    plan = {"kwp": {"engine": {}, "tcm_cvt": {}, "bcm": {}, "ipdm": {}}}
    assert est.cadencia_total(plan) == {"engine": 1, "tcm_cvt": 1, "bcm": 1, "ipdm": 1}


def test_sequencia_andando_bem_formada_e_so_com_alvos_de_velocidade():
    ids = [s.id for s in est.ANDANDO]
    assert len(ids) == len(set(ids)) >= 12
    assert est.ANDANDO[0].id == "repouso"
    assert 180 <= est.duracao_total(est.ANDANDO) <= 600
    for s in est.ANDANDO:
        assert s.texto.strip() and s.duracao_s >= 5
    alvos = [s.id for s in est.ANDANDO if s.id.startswith("mantem_")]
    assert len(alvos) >= 4          # patamares de velocidade constante para calibrar as rodas


def test_sequencia_puxada_tem_aviso_de_local_seguro_e_repete_a_puxada():
    ids = [s.id for s in est.PUXADA]
    assert ids[0] == "repouso" and len(ids) == len(set(ids))
    assert sum(i.startswith("puxada_") and not i.endswith("_solta") for i in ids) >= 3
    assert any("local" in s.texto.lower() and "seguro" in s.texto.lower() for s in est.PUXADA[:3])
    assert 120 <= est.duracao_total(est.PUXADA) <= 420
