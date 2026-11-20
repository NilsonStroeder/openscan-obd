"""Roteiro de estímulos com horário: instrui o motorista, passo a passo, e marca cada um no log.

Só fala com a pessoa (tela e bipe) e escreve marcas `{"event": "estimulo", ...}` no mesmo arquivo da
gravação, com o mesmo relógio (`time.time()`), para cruzar depois com os bytes. Não envia nada ao carro.
Sequência pensada para o carro PARADO, motor ligado, em P, freio de mão puxado.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable

AVISO_S = 3  # antecedência do aviso "a seguir"


@dataclass(frozen=True)
class Estimulo:
    id: str
    texto: str
    duracao_s: float


PARADO: list[Estimulo] = [
    Estimulo("repouso", "Não mexa em nada (referência)", 20),
    Estimulo("freio_on", "Pise no FREIO até o fundo e segure", 6),
    Estimulo("freio_off", "Solte o freio", 6),
    Estimulo("pedal_leve", "Em P, pise LEVE no acelerador (~1500 rpm) e segure", 6),
    Estimulo("pedal_leve_off", "Solte o acelerador", 8),
    Estimulo("pedal_medio", "Em P, pise no acelerador até ~2500 rpm e segure", 6),
    Estimulo("pedal_medio_off", "Solte o acelerador", 8),
    Estimulo("pedal_forte", "Em P, pise até ~3500 rpm por 3 s (não bata no limitador)", 4),
    Estimulo("pedal_forte_off", "Solte o acelerador", 10),
    Estimulo("volante_esq", "Gire o volante todo para a ESQUERDA e segure", 6),
    Estimulo("volante_centro1", "Volante no centro", 5),
    Estimulo("volante_dir", "Gire o volante todo para a DIREITA e segure", 6),
    Estimulo("volante_centro2", "Volante no centro", 5),
    Estimulo("farol_baixo", "Ligue o FAROL BAIXO", 8),
    Estimulo("farol_alto", "Ligue o FAROL ALTO", 8),
    Estimulo("farol_off", "Desligue os faróis", 6),
    Estimulo("seta_esq", "Ligue a SETA ESQUERDA", 8),
    Estimulo("seta_dir", "Troque para a SETA DIREITA", 8),
    Estimulo("seta_off", "Desligue a seta", 5),
    Estimulo("alerta", "Ligue o PISCA-ALERTA", 8),
    Estimulo("alerta_off", "Desligue o pisca-alerta", 5),
    Estimulo("porta_mot", "Abra a PORTA do motorista e deixe aberta", 7),
    Estimulo("porta_mot_off", "Feche a porta do motorista", 6),
    Estimulo("porta_pass", "Abra a PORTA do passageiro (alguém abre) e deixe aberta", 7),
    Estimulo("porta_pass_off", "Feche a porta do passageiro", 6),
    Estimulo("ar_on", "Ligue o AR-CONDICIONADO (A/C) no frio máximo", 15),
    Estimulo("ventilador_max", "Ventilador no MÁXIMO", 8),
    Estimulo("ar_off", "Desligue o A/C e o ventilador", 10),
    Estimulo("desemb_on", "Ligue o DESEMBAÇADOR traseiro", 8),
    Estimulo("desemb_off", "Desligue o desembaçador traseiro", 6),
    Estimulo("limpador", "Ligue o LIMPADOR de para-brisa (1 velocidade)", 8),
    Estimulo("limpador_off", "Desligue o limpador", 5),
    Estimulo("cambio_r", "Com o pé no FREIO: engate R e segure", 8),
    Estimulo("cambio_n1", "Com o pé no FREIO: passe para N e segure", 8),
    Estimulo("cambio_d", "Com o pé no FREIO: engate D e segure", 10),
    Estimulo("cambio_n2", "Com o pé no FREIO: volte para N e segure", 8),
    Estimulo("cambio_p", "Com o pé no FREIO: volte para P", 8),
    Estimulo("fim_repouso", "Solte o freio e não mexa em nada (referência final)", 15),
]


# Carro ANDANDO, em via reta e livre, respeitando SEMPRE o limite da via (pule o que não for permitido).
# Quem dirige não mexe no notebook; os avisos são automáticos. Patamares constantes calibram as rodas no CAN.
ANDANDO: list[Estimulo] = [
    Estimulo("repouso", "Parado em P, motor ligado: não mexa em nada", 10),
    Estimulo("arranque_suave", "Pé no freio, engate D e arranque SUAVE até ~30 km/h", 15),
    Estimulo("mantem_30", "Mantenha 30 km/h constante", 20),
    Estimulo("sobe_50", "Acelere suave até 50 km/h", 10),
    Estimulo("mantem_50", "Mantenha 50 km/h constante", 20),
    Estimulo("sobe_70", "Acelere suave até 70 km/h (ou o limite da via)", 10),
    Estimulo("mantem_70", "Mantenha 70 km/h constante (ou o limite da via)", 20),
    Estimulo("od_off_70", "Aperte O/D OFF (overdrive desligado; a luz acende no painel) e mantenha a mesma velocidade", 20),
    Estimulo("od_on_70", "Aperte O/D OFF de novo (overdrive religado) e mantenha a mesma velocidade", 20),
    Estimulo("sobe_90", "Se a via permitir, acelere suave até 90 km/h; senão mantenha o limite", 12),
    Estimulo("mantem_90", "Mantenha a velocidade constante (90 km/h se permitido)", 20),
    Estimulo("solta_acelerador", "Solte o acelerador e deixe desacelerar SEM frear", 15),
    Estimulo("freada_leve", "Freie suave até ~30 km/h", 10),
    Estimulo("mantem_30b", "Mantenha 30 km/h constante", 12),
    Estimulo("arrancada_firme", "Pise firme (~70% do pedal) até ~60 km/h, sem ultrapassar o limite, e solte", 12),
    Estimulo("solta2", "Deixe desacelerar sem frear", 10),
    Estimulo("freada_parar", "Freie até parar e engate P", 20),
    Estimulo("fim_repouso", "Parado em P, motor ligado: não mexa em nada (temperatura do fluido no fim)", 20),
]


# Puxada controlada: SÓ em local seguro e permitido (pista fechada, estrada particular, dinamômetro).
# Em via pública não ultrapasse o limite: nesse caso pule este roteiro. Use com o motor já aquecido (>80 °C).
PUXADA: list[Estimulo] = [
    Estimulo("repouso", "Local seguro e permitido, parado em P, motor aquecido: não mexa em nada", 10),
    Estimulo("aquece", "Engate D e ande a ~40 km/h constante, em linha reta", 15),
    Estimulo("puxada_1", "PUXADA 1: pise o acelerador até o FUNDO e segure", 10),
    Estimulo("puxada_1_solta", "Solte o acelerador e deixe desacelerar até ~40 km/h, sem frear", 15),
    Estimulo("puxada_2", "PUXADA 2: acelerador até o FUNDO e segure", 10),
    Estimulo("puxada_2_solta", "Solte e deixe desacelerar até ~40 km/h, sem frear", 15),
    Estimulo("puxada_3", "PUXADA 3: acelerador até o FUNDO e segure", 10),
    Estimulo("puxada_3_solta", "Solte e deixe desacelerar sem frear", 15),
    Estimulo("freada_parar", "Freie até parar e engate P", 15),
    Estimulo("fim_repouso", "Parado em P: não mexa em nada", 10),
]


def duracao_total(passos: list[Estimulo]) -> float:
    return sum(p.duracao_s for p in passos)


def _bipe() -> None:
    try:
        import winsound
        winsound.Beep(1000, 200)
    except Exception:
        print("\a", end="", flush=True)


def run_estimulos(passos: list[Estimulo], marcar: Callable[[dict], None], *,
                  say: Callable[[str], None] = print, beep: Callable[[], None] = _bipe,
                  sleep: Callable[[float], None] = time.sleep, wall: Callable[[], float] = time.time,
                  parar: threading.Event | None = None) -> bool:
    """Executa os passos em tempo fixo. Devolve True se completou. Cada passo vira uma marca no log."""
    parar = parar or threading.Event()
    marcar({"event": "estimulos_started", "t": round(wall(), 3), "n": len(passos),
            "duracao_s": duracao_total(passos)})
    completos = True
    for i, p in enumerate(passos):
        if parar.is_set():
            completos = False
            break
        beep()
        marcar({"event": "estimulo", "t": round(wall(), 3), "id": p.id, "texto": p.texto, "dur_s": p.duracao_s})
        say(f"[{i + 1}/{len(passos)}] AGORA: {p.texto}  ({p.duracao_s:g} s)")
        aviso = min(AVISO_S, p.duracao_s) if i + 1 < len(passos) else 0
        sleep(p.duracao_s - aviso)
        if aviso:
            say(f"    a seguir: {passos[i + 1].texto}")
            sleep(aviso)
        if parar.is_set():
            completos = False
            break
    marcar({"event": "estimulos_finished", "t": round(wall(), 3), "completos": completos})
    return completos


def cadencia_total(plan: dict) -> dict[str, int]:
    """Com estímulos curtos (4–20 s), lê todos os módulos a cada ciclo para não perder o evento."""
    return {nome: 1 for nome in plan["kwp"]}
