"""
Roteiro guiado do teste no carro — uma etapa de cada vez.

Como usar:
    dois cliques em roteiro.bat (na pasta do projeto)
ou, no PowerShell, na pasta do projeto:
    .\\.venv\\Scripts\\python.exe roteiro_carro.py

Em cada etapa:
    ENTER  = fazer esta etapa
    ESC    = pular para a próxima
    Ctrl+C = durante uma etapa, para só a etapa (os dados já gravados ficam)

Opções:
    --de N       começa na etapa N (ex.: --de 4)
    --listar     só mostra as etapas e os comandos, sem rodar nada
    --dll CAM    caminho da DLL J2534 (padrão: GODIAG)

Tudo é leitura: sessão de diagnóstico, leitura de dados e de códigos de
falha. Nenhuma etapa apaga código de falha nem grava nada no carro.
Comandos equivalentes: veja `openscan-obd --help`.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import os
import signal
import struct
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
DEFAULT_DLL = r"C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll"

ENTER_KEYS = ("\r", "\n")
ESC_KEY = "\x1b"


@dataclass
class Etapa:
    titulo: str
    condicao: str
    instrucoes: list[str]
    comandos: list[list[str]]
    tempo: str
    para_sozinho_em_s: int | None = None      # usado pelo dashboard
    durante: list[str] = field(default_factory=list)
    # Nome base para salvar a saída de tela de cada comando em logs/
    salvar_saida_como: list[str] | None = None
    # Pedido mostrado antes de cada comando; espera ENTER (ESC pula aquele comando).
    pedir_antes: list[str] | None = None


def _agora() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def cli(*args: str) -> list[str]:
    return ["-m", "openscan_obd.cli", *args]


def car(*args: str) -> list[str]:
    return [str(ROOT / "car_session.py"), *args]


def montar_etapas(dll: str) -> list[Etapa]:
    meta = ["--vehicle", "Sentra B16 2010", "--ecu", "ECM 0x7E0", "--adapter", "GODIAG GD101"]
    ordem_seletor = (("P", 1), ("N", 1), ("D", 1), ("R", 1),
                     ("R", 2), ("D", 2), ("N", 2), ("P", 2))
    # Só o LID 0x01 do TCM, pelo mesmo caminho dos snapshots de 2026-10-23.
    seletor = [
        cli("snapshot", "--dll", dll, "--only", "tcm_cvt", "--label", f"seletor_{cen}_{n}",
            "--start", "01", "--end", "01")
        for cen, n in ordem_seletor
    ]
    pedir_seletor = [f"Coloque a alavanca em {cen} (pé no freio)" for cen, _ in ordem_seletor]
    return [
        Etapa(
            titulo="Teste do adaptador (em casa ou no carro)",
            condicao="GD101 ligado no USB; não precisa estar no carro.",
            instrucoes=["Ligue o cabo USB do GD101 no notebook.",
                        "Não precisa ligar no carro. Só esperar a mensagem.",
                        "Se aparecer OK, está tudo certo. Se aparecer FALHA,",
                        "tire e coloque o cabo USB de novo e aperte R para repetir."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Partida a frio (TCM antes de ligar)",
            condicao="Carro FRIO (parado a noite toda). Ignição LIGADA, motor DESLIGADO.",
            instrucoes=["Conecte o cabo do GD101 no carro.",
                        "Gire a chave até acender o painel, mas NÃO dê partida."],
            comandos=[cli("snapshot", "--dll", dll, "--only", "tcm_cvt", "--label", "frio_antes_ligar")],
            tempo="2 min",
        ),
        Etapa(
            titulo="Partida a frio (15 min aquecendo)",
            condicao="Logo depois da etapa anterior. Carro parado, em P.",
            instrucoes=["Depois de apertar ENTER, espere aparecer as linhas com RPM.",
                        "Aí LIGUE O MOTOR e anote a hora.",
                        "Deixe em marcha lenta, em P, sem acelerar, até a etapa acabar sozinha."],
            comandos=[car("correlated", "--dll", dll, "--duration", "900", "--label", "partida_frio")],
            tempo="15 min",
            durante=["Ligue o motor agora. Não acelere."],
        ),
        Etapa(
            titulo="Dashboard falando com o ECM",
            condicao="Carro parado, motor ligado, em P.",
            instrucoes=["Depois de apertar ENTER, abra no navegador: http://127.0.0.1:8000",
                        "Só observe. A etapa para sozinha em 5 minutos."],
            comandos=[cli("dashboard", "--hardware", "--dll", dll, "--profile", "nissan-sentra-b16-2010",
                          "--capture", "logs\\gateway_ecm_{agora}.jsonl", *meta)],
            tempo="5 min",
            para_sozinho_em_s=300,
        ),
        Etapa(
            titulo="Scan OBD-II (PIDs, VIN, códigos de falha)",
            condicao="Carro parado, motor ligado.",
            instrucoes=["Só esperar terminar."],
            comandos=[cli("scan", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["scan_obd"],
        ),
        Etapa(
            titulo="Códigos de falha via KWP (motor e câmbio)",
            condicao="Carro parado, motor ligado.",
            instrucoes=["Só esperar terminar. É só leitura, não apaga nada.",
                        "São 4 leituras (motor e câmbio, de dois jeitos). "
                        "Se uma der erro, tudo bem: o erro também fica gravado."],
            comandos=[
                cli("read-kwp-dtcs", "--dll", dll, "--txid", t, "--rxid", r,
                    "--session", "C0", "--status-mask", "FF", *grupo, "--json")
                for t, r in (("7E0", "7E8"), ("7E1", "7E9"))
                for grupo in ((), ("--group", "FF00"))
            ],
            tempo="2 min",
            salvar_saida_como=["kwp_dtc_ecm", "kwp_dtc_ecm_grupo",
                               "kwp_dtc_tcm", "kwp_dtc_tcm_grupo"],
        ),
        Etapa(
            titulo="Varredura de dados do ECM",
            condicao="Carro parado, motor ligado.",
            instrucoes=["Só esperar terminar. Vai mostrar um contador."],
            comandos=[car("ecm", "--dll", dll)],
            tempo="5 min",
            salvar_saida_como=["car_ecm"],
        ),
        Etapa(
            titulo="Procurar módulos (faixa 600 e 700)",
            condicao="Carro parado, motor ligado (para não descarregar a bateria).",
            instrucoes=["Só esperar terminar. Demora."],
            comandos=[cli("discover", "--dll", dll, "--start", "600", "--end", "6FF"),
                      cli("discover", "--dll", dll, "--start", "700", "--end", "7FF")],
            tempo="10 min",
            salvar_saida_como=["discover_600", "discover_700"],
        ),
        Etapa(
            titulo="Ler outros módulos (0x71E, BCM, IPDM, EPS, painel)",
            condicao="Carro parado, motor ligado (para não descarregar a bateria).",
            instrucoes=["Só esperar terminar."],
            comandos=[car(m, "--dll", dll) for m in ("unk71e", "bcm", "ipdm", "eps", "meter")],
            tempo="10 min",
            salvar_saida_como=["car_unk71e", "car_bcm", "car_ipdm", "car_eps", "car_meter"],
        ),
        Etapa(
            titulo="Alavanca do câmbio P / N / D / R",
            condicao="Carro parado, motor ligado, PÉ FIRME NO FREIO o tempo todo.",
            instrucoes=["São 8 leituras, nesta ordem: P, N, D, R, R, D, N, P.",
                        "Antes de cada uma, a tela pede a posição da alavanca.",
                        "Quem está no volante muda a alavanca; aí aperte ENTER."],
            comandos=seletor,
            pedir_antes=pedir_seletor,
            tempo="8 min",
        ),
        Etapa(
            titulo="Ré com várias leituras",
            condicao="Carro parado, motor ligado, PÉ FIRME NO FREIO.",
            instrucoes=["O programa vai pedir para colocar em R e depois voltar para P.",
                        "Aperte ENTER quando ele pedir."],
            comandos=[car("reverse", "--dll", dll)],
            tempo="2 min",
        ),
        Etapa(
            titulo="Acelerar parado em P",
            condicao="Carro parado, em P.",
            instrucoes=["Depois de apertar ENTER, quem está no volante acelera em degraus:",
                        "solto 10 s -> leve 10 s -> médio 10 s -> solto. Repetir até acabar (2 min)."],
            comandos=[car("correlated", "--dll", dll, "--duration", "120", "--label", "acel_em_P")],
            tempo="2 min",
        ),
        Etapa(
            titulo="Rodando (20 min)",
            condicao="Carro em movimento. NÃO mexer no notebook enquanto anda.",
            instrucoes=["Aperte ENTER ainda parado e deixe o notebook quieto.",
                        "Trânsito normal, algumas arrancadas.",
                        "Se der: 1 minuto acima de 80 km/h, e 30 s a ~100 km/h com pouco acelerador.",
                        "Respeite o limite da via. Se não der, tudo bem: grava o que der."],
            comandos=[car("correlated", "--dll", dll, "--duration", "1200", "--label", "estrada")],
            tempo="20 min",
        ),
    ]


def montar_etapas_proximo(dll: str) -> list[Etapa]:
    """Só o que falta validar no carro (SDD 2026-11-15): dashboard v2, scan, probe-dtc, estrada."""
    meta = ["--vehicle", "Sentra B16 2010", "--ecu", "ECM 0x7E0", "--adapter", "GODIAG GD101"]

    def dash(prefixo: str) -> list[str]:
        return cli("dashboard", "--hardware", "--dll", dll, "--profile", "nissan-sentra-b16-2010",
                   "--capture", f"logs\\{prefixo}_{{agora}}.jsonl", *meta)

    return [
        Etapa(
            titulo="Teste do adaptador",
            condicao="GD101 ligado no USB; não precisa estar no carro.",
            instrucoes=["Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Dashboard v2 parado (motor ligado, em P)",
            condicao="GD101 no carro, motor ligado em marcha lenta, em P, freio de mão puxado.",
            instrucoes=["Depois do ENTER, abra http://127.0.0.1:8000 e só observe.",
                        "Confira na aba Geral: quente, RPM ~710 e líquido ~94 °C; frio, RPM mais alto (1000+) e líquido subindo aos poucos.",
                        "A tensão deve ficar perto de 14 V. Em motor frio, o líquido subir durante os 6 min já é um bom teste.",
                        "Cada card deve ter selo 'padrão'. Anote qualquer card em '—' e o motivo mostrado.",
                        "Na aba CVT: o status do TCM deve dizer 'respondendo'. Para sozinha em 6 min."],
            comandos=[dash("gateway_v2_parado")],
            tempo="6 min",
            para_sozinho_em_s=360,
        ),
        Etapa(
            titulo="Dashboard v2: alavanca P / N / D / R",
            condicao="Motor ligado, PÉ FIRME NO FREIO o tempo todo, carro parado.",
            instrucoes=["Depois do ENTER, abra a aba CVT em http://127.0.0.1:8000.",
                        "Ordem, ~15 s em cada: P, N, D, R, D, N, P. Veja se 'Posição' e 'Ré engatada' acompanham.",
                        "Anote qualquer atraso ou posição errada. Temperatura ATF deve estar com selo 'estimado'.",
                        "Para sozinha em 5 min."],
            comandos=[dash("gateway_v2_alavanca")],
            tempo="5 min",
            para_sozinho_em_s=300,
        ),
        Etapa(
            titulo="Dashboard v2: botão Scan",
            condicao="Motor ligado, em P, freio de mão puxado.",
            instrucoes=["Depois do ENTER, abra http://127.0.0.1:8000, aba Scan, e clique em Iniciar scan.",
                        "A leitura ao vivo pausa durante o scan e deve voltar sozinha ao terminar.",
                        "Na aba Falhas: o CVT NUNCA pode aparecer como 'sem falhas'.",
                        "O arquivo fica em logs\\scan_*.json. Para sozinha em 5 min."],
            comandos=[dash("gateway_v2_scan")],
            tempo="5 min",
            para_sozinho_em_s=300,
        ),
        Etapa(
            titulo="Varredura completa de LIDs do ECM (caçar o pulso de injeção)",
            condicao="Motor ligado em marcha lenta, em P, freio de mão puxado. Dashboard fechado.",
            instrucoes=["Lê os LIDs 0x00 a 0xFF do ECM, só com o serviço 0x21 (leitura). Não grava nada.",
                        "É a única chance de achar o pulso de injeção: o ECM não tem PID padrão para ele.",
                        "Cada LID sem resposta espera até 1,5 s; pode levar até uns 7 minutos.",
                        "Guarde o resultado: logs\\ecm_lid_sweep_*.json."],
            comandos=[car("ecm_sweep_full", "--dll", dll)],
            tempo="7 min",
            salvar_saida_como=["ecm_sweep_full"],
        ),
        Etapa(
            titulo="Falhas do câmbio: hipóteses H1 a H3 (sem A3)",
            condicao="Motor ligado, em P, freio de mão puxado. Dashboard fechado (um programa por vez).",
            instrucoes=["Só leitura: OBD 03/07/0A no câmbio e por broadcast, KWP 13/17 no motor e no câmbio.",
                        "Resposta ruim ou sem resposta é resultado válido: fica gravada crua em logs\\probe_dtc_*.json."],
            comandos=[cli("probe-dtc", "--dll", dll)],
            tempo="2 min",
            salvar_saida_como=["probe_dtc_h1_h3"],
        ),
        Etapa(
            titulo="Falhas do câmbio: SID A3 (hipótese H5)",
            condicao="Só depois da etapa anterior. Carro parado em P, freio de mão puxado, motor ligado.",
            instrucoes=["O A3 tem semântica desconhecida (fonte da comunidade). Um pedido por módulo.",
                        "Para na primeira resposta inesperada. Se a etapa anterior deu algo estranho, ESC.",
                        "O resultado é hipótese não verificada."],
            comandos=[cli("probe-dtc", "--dll", dll, "--allow-a3", "--confirm-parked")],
            pedir_antes=["Confirme: carro parado em P, freio de mão puxado, motor ligado, ninguém mexendo no carro"],
            tempo="2 min",
            salvar_saida_como=["probe_dtc_a3"],
        ),
        Etapa(
            titulo="Estrada com dashboard e captura (20 min)",
            condicao="Carro em movimento. NÃO mexer no notebook enquanto anda.",
            instrucoes=["Aperte ENTER ainda parado. Antes de sair: engate R por ~10 s e volte para D.",
                        "Trânsito normal com algumas arrancadas.",
                        "Se der: 1 min acima de 80 km/h e 30 s a ~100 km/h com pouco acelerador (lock-up).",
                        "Respeite o limite da via. Para sozinha em 21 min."],
            comandos=[dash("gateway_v2_estrada")],
            tempo="20 min",
            para_sozinho_em_s=1260,
        ),
    ]


def montar_etapas_varredura(dll: str) -> list[Etapa]:
    """Varredura longa de todos os IDs CAN (0x600-0x7FF), só leitura, ignição ligada."""
    return [
        Etapa(
            titulo="Teste do adaptador",
            condicao="GD101 ligado no USB e no carro.",
            instrucoes=["Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Varredura de todos os módulos (IDs 0x700 a 0x7FF)",
            condicao="Ignição ligada (motor ligado, em P, freio de mão puxado, para não descarregar a bateria).",
            instrucoes=["Testa cada ID com um pedido de sessão de diagnóstico e, onde alguém responde, só lê "
                        "identificação e falhas. Não grava nem apaga nada.",
                        "Pode levar alguns minutos; mostra o progresso. O arquivo é regravado a cada ID.",
                        "Se a tela parar por mais de 3 min, feche a janela (Ctrl+C não funciona com o adaptador "
                        "travado), tire e ponha o cabo USB: o que já foi achado fica no arquivo.",
                        "Resultado: logs\\scan_all_*.json."],
            comandos=[cli("scan-all", "--dll", dll)],
            tempo="10 min",
            # sem salvar_saida_como: a saída é capturada e só aparece no fim; aqui o progresso é ao vivo
            # (o resultado já vai para logs\\scan_all_*.json).
        ),
    ]


def montar_etapas_pendentes(dll: str) -> list[Etapa]:
    """Os dois testes parados que faltam (2026-11-18): scan-22 no câmbio e dashboard com tcm_every=1."""
    meta = ["--vehicle", "Sentra B16 2010", "--ecu", "ECM 0x7E0", "--adapter", "GODIAG GD101"]
    return [
        Etapa(
            titulo="Teste do adaptador",
            condicao="GD101 ligado no USB e no carro.",
            instrucoes=["Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Serviço 0x22 no câmbio (DIDs 0x1E00 a 0x1EFF)",
            condicao="Ignição ligada (motor ligado, em P, freio de mão puxado).",
            instrucoes=["Só leitura: pergunta ao câmbio (0x7E1) o que ele guarda em cada DID. É o que o aparelho "
                        "do seu amigo parece usar (1EBC, 1EC0, 1EC1).",
                        "Se o câmbio recusar logo no começo, a varredura para sozinha: isso também é resultado.",
                        "Resultado: logs\\scan_22_7E1_*.json. Mande esse arquivo para o Claude."],
            comandos=[cli("scan-22", "--dll", dll, "--txid", "7E1", "--rxid", "7E9")],
            tempo="3 min",
            # sem salvar_saida_como: o progresso aparece ao vivo
        ),
        Etapa(
            titulo="Dashboard parado: câmbio e motor em sincronia (e LTFT)",
            condicao="Motor ligado em marcha lenta, em P, freio de mão puxado. De preferência motor quente.",
            instrucoes=["Depois do ENTER, abra http://127.0.0.1:8000.",
                        "Aba CVT: a rotação do câmbio deve acompanhar a do motor, sem defasagem.",
                        "Aba Geral: anote o ajuste de combustível de longo prazo (LTFT); antes deu +20,3 %.",
                        "Para sozinha em 6 min."],
            comandos=[cli("dashboard", "--hardware", "--dll", dll, "--profile", "nissan-sentra-b16-2010",
                          "--capture", "logs\\gateway_v2_pendentes_{agora}.jsonl", *meta)],
            tempo="6 min",
            para_sozinho_em_s=360,
        ),
    ]


def montar_etapas_estrada(dll: str) -> list[Etapa]:
    """Teste em movimento: captura do dashboard por ~20 min (relação do CVT, pressão de linha, lock-up)."""
    meta = ["--vehicle", "Sentra B16 2010", "--ecu", "ECM 0x7E0", "--adapter", "GODIAG GD101"]
    return [
        Etapa(
            titulo="Teste do adaptador",
            condicao="GD101 no carro, notebook preso/apoiado com segurança.",
            instrucoes=["Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Estrada com dashboard e captura (20 min)",
            condicao="Carro em movimento. Quem dirige NÃO mexe no notebook; o teste é feito por um passageiro "
                     "ou só captura e se analisa depois.",
            instrucoes=["Aperte ENTER ainda parado, motor ligado, em P.",
                        "Antes de sair: pé no freio, engate R por ~10 s e volte para D.",
                        "Trânsito normal com algumas arrancadas leves e outras mais firmes.",
                        "Se der: 1 min acima de 80 km/h e 30 s a ~100 km/h com pouco acelerador (lock-up).",
                        "Respeite o limite da via. Para sozinha em 21 min.",
                        "Resultado: logs\\gateway_v2_estrada_*.jsonl. Mande para o Claude analisar."],
            comandos=[cli("dashboard", "--hardware", "--dll", dll, "--profile", "nissan-sentra-b16-2010",
                          "--capture", "logs\\gateway_v2_estrada_{agora}.jsonl", *meta)],
            tempo="20 min",
            para_sozinho_em_s=1260,
        ),
    ]


def montar_etapas_coleta(dll: str, fuel: str = "etanol") -> list[Etapa]:
    """Coleta ampla, só leitura: descoberta parado, 15 min gravando tudo dirigindo, 5 min só escutando o CAN."""
    return [
        Etapa(
            titulo="Teste do adaptador",
            condicao="GD101 no carro, notebook preso/apoiado com segurança.",
            instrucoes=["Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R."],
            comandos=[cli("j2534-check", "--dll", dll)],
            tempo="1 min",
            salvar_saida_como=["j2534_check"],
        ),
        Etapa(
            titulo="Descoberta parado (PIDs e LIDs que o carro responde)",
            condicao="Carro parado, motor ligado, em P, freio de mão puxado, sem mexer em nada.",
            instrucoes=["Testa todos os PIDs, inclusive os que a ECU não declara, e todos os LIDs de cada módulo.",
                        "Inclui os DIDs 1100-12FF do serviço 22 (onde outros Nissan guardam temperaturas e pressão de óleo). Só leitura. A varredura 0000-FFFF fica em outro roteiro "
                        "(roteiro_dids.bat)."],
            comandos=[cli("collect-discover", "--dll", dll, "--profile", "nissan-sentra-b16-2010", "--dids", "1100-12FF")],
            tempo="~3 min",
            salvar_saida_como=["coleta_descoberta"],
        ),
        Etapa(
            titulo="Gravação ampla dirigindo (15 min)",
            condicao="Carro em movimento. Quem dirige NÃO mexe no notebook; o teste é feito por um passageiro "
                     "ou só captura e se analisa depois.",
            instrucoes=["Aperte ENTER ainda parado, em P.",
                        "Antes de sair: pé no freio, engate R por ~10 s e volte para D.",
                        "Trânsito normal, arrancadas leves e firmes, algumas frenagens e curvas; se der, um trecho "
                        "a 80-100 km/h com pouco acelerador.",
                        f"Combustível registrado: {fuel}. Para mudar, use --fuel no .bat.",
                        "Termina sozinha em 15 min. Resultado: logs\\coleta_*.jsonl."],
            comandos=[cli("collect", "--dll", dll, "--minutes", "15", "--fuel", fuel)],
            tempo="15 min",
            para_sozinho_em_s=1080,
        ),
        Etapa(
            titulo="Escuta passiva do CAN (5 min)",
            condicao="Carro em movimento, igual à etapa anterior. Nada é enviado ao carro.",
            instrucoes=["Grava todo quadro que o carro transmite sozinho (rodas, pedais, painel).",
                        "Acelere, freie e vire o volante algumas vezes de forma bem marcada.",
                        "Termina sozinha em 5 min. Resultado: logs\\sniff_*.jsonl."],
            comandos=[cli("sniff", "--dll", dll, "--minutes", "5", "--fuel", fuel)],
            tempo="5 min",
            para_sozinho_em_s=360,
        ),
    ]


def montar_etapas_dids(dll: str) -> list[Etapa]:
    """Varredura longa do serviço 22 (0000-FFFF) nos módulos que o aceitam. Roda numa viagem, carro ligado."""
    return [
        montar_etapas_coleta(dll)[0],
        Etapa(
            titulo="Varredura longa do serviço 22 (DIDs 0000-FFFF)",
            condicao="Carro ligado em P, freio de mão puxado, em local ventilado; ou em viagem com notebook preso.",
            instrucoes=["Testa o serviço 22 em cada módulo; só varre os que o aceitam (~45 min cada).",
                        "Só leitura. Pode interromper com Ctrl+C: o que já achou fica salvo no JSON."],
            comandos=[cli("collect-discover", "--dll", dll, "--profile", "nissan-sentra-b16-2010", "--dids", "todos")],
            tempo="45 min a algumas horas",
            salvar_saida_como=["coleta_descoberta_dids"],
        ),
    ]


def montar_etapas_descoberta(dll: str) -> list[Etapa]:
    """Só a descoberta, com o carro parado e ligado (pode ser feita agora; a gravação usa o resultado depois)."""
    return montar_etapas_coleta(dll)[:2]


def montar_etapas_gravacao(dll: str, fuel: str = "etanol") -> list[Etapa]:
    """Só a parte em movimento (gravação 15 min + escuta do CAN 5 min); usa a descoberta mais recente."""
    return [montar_etapas_coleta(dll, fuel)[0], *montar_etapas_coleta(dll, fuel)[2:]]


def montar_etapas_guiado(dll: str, fuel: str = "etanol") -> list[Etapa]:
    """Carro parado e ligado: o roteiro manda um estímulo por vez (freio, pedal, volante, luzes, portas, A/C, câmbio)
    e marca a hora de cada um no log. Roda duas vezes a mesma sequência: coleta OBD/LID/DID e escuta do CAN."""
    from openscan_obd.gateway.estimulos import PARADO, duracao_total
    seg = int(duracao_total(PARADO)) + 60
    cond = ("Carro PARADO, motor ligado, em P, freio de mão puxado, local ventilado. Notebook no colo ou apoiado; "
            "as instruções aparecem na tela e há um bipe a cada passo. Pé no freio SEMPRE ao mexer no câmbio.")
    return [
        montar_etapas_coleta(dll, fuel)[0],
        Etapa(
            titulo="Coleta guiada (OBD + LIDs + DIDs) com estímulos marcados",
            condicao=cond,
            instrucoes=["Siga cada instrução assim que ela aparecer; a hora é marcada sozinha.",
                        "Use a descoberta mais recente. Resultado: logs\\coleta_*.jsonl (com linhas 'estimulo')."],
            comandos=[cli("collect", "--dll", dll, "--estimulos", "parado", "--fuel", fuel)],
            tempo="~5 min",
            para_sozinho_em_s=seg,
        ),
        Etapa(
            titulo="Escuta do CAN guiada, mesma sequência",
            condicao=cond,
            instrucoes=["Repita exatamente os mesmos passos, com o mesmo ritmo.",
                        "Resultado: logs\\sniff_*.jsonl (com linhas 'estimulo')."],
            comandos=[cli("sniff", "--dll", dll, "--estimulos", "parado", "--fuel", fuel)],
            tempo="~5 min",
            para_sozinho_em_s=seg,
        ),
    ]


def montar_etapas_guiado_andando(dll: str, fuel: str = "etanol") -> list[Etapa]:
    """Carro andando em via reta: patamares de 30/50/70/90 km/h com avisos automáticos e hora marcada.
    Mesma sequência duas vezes (coleta OBD, depois escuta do CAN) para calibrar velocidade das rodas, etc."""
    from openscan_obd.gateway.estimulos import ANDANDO, PUXADA, duracao_total
    seg = int(duracao_total(ANDANDO)) + 60
    cond = ("Carro em movimento, em via reta e livre (2–3 km), RESPEITANDO O LIMITE. Quem dirige NÃO mexe no notebook: "
            "os avisos são sozinhos (bipe + tela). Um passageiro pode ler a tela. Se um passo não for seguro ou "
            "permitido, ignore-o e siga dirigindo com segurança.")
    preparo = dataclasses.replace(
        montar_etapas_coleta(dll, fuel)[0],
        titulo="Preparação e teste do adaptador",
        condicao="Antes de ligar o carro. Leia tudo; só então aperte ENTER.",
        instrucoes=[
            "FECHE o dashboard e qualquer janela/terminal que use o adaptador (só um programa por vez fala com o GD101).",
            "Notebook: na tomada ou com bateria cheia; desligue a suspensão/hibernação; apoiado com segurança, nunca solto no banco.",
            "Se tiver multímetro: meça a bateria com o carro FRIO e DESLIGADO (esperado ~12,4–12,7 V; abaixo de 12,0 V é suspeito) e anote.",
            "Use a PRIMEIRA PARTIDA do dia, sem aquecer o motor antes: a subida de temperatura do fluido do câmbio ajuda a decodificar.",
            "Ar-condicionado: o que decidir (ligado ou desligado), mantenha igual do começo ao fim do roteiro.",
            "Ligue o carro, engate P, puxe o freio de mão. Ligue o GD101 no carro e no notebook.",
            "Se aparecer OK, siga. Se aparecer FALHA, tire e ponha o cabo USB e aperte R.",
        ],
    )
    erros_antes = Etapa(
        titulo="Ler códigos de falha ANTES de andar",
        condicao="Carro ligado, em P, freio de mão puxado, ainda frio. Dashboard fechado.",
        instrucoes=["Só leitura: não apaga nada. Resposta 'sem resposta' NÃO quer dizer sem falhas.",
                    "Resultado: logs\\erros_antes_*.txt (para ler) e .json (cru)."],
        comandos=[cli("ler-erros", "--dll", dll, "--label", "antes")],
        tempo="1 min",
    )
    erros_depois = Etapa(
        titulo="Ler códigos de falha DEPOIS de andar",
        condicao=("Pare em P, freio de mão puxado, SEM DESLIGAR O MOTOR (nem a ignição) desde o fim do trajeto. "
                  "Dashboard fechado."),
        instrucoes=["Mostra se apareceu algum código novo depois de andar e de puxar.",
                    "Resultado: logs\\erros_depois_*.txt e .json. Depois pode desligar o carro.",
                    "No fim, mande para análise os dois erros_*.txt e os coleta_*/sniff_* novos."],
        comandos=[cli("ler-erros", "--dll", dll, "--label", "depois")],
        tempo="1 min",
    )
    trajeto = Etapa(
        titulo="Gravar o trajeto de casa até a estrada (partida a frio)",
        condicao=("Logo depois da leitura de códigos, ainda em casa, motor frio. Aperte ENTER e SAIA DIRIGINDO normalmente "
                  "até a estrada: a gravação (11 min) para sozinha, ninguém precisa mexer no notebook."),
        instrucoes=["Grava tudo de OBD e dos módulos desde a partida a frio: a subida da temperatura do fluido do câmbio "
                    "e do motor ajuda a decodificar o TCM, e o trânsito normal serve de dado extra.",
                    "Respeite o trânsito e o limite. Quem dirige NÃO mexe no notebook.",
                    "Chegou à estrada antes dos 11 min? Pare em local seguro, em P, e espere acabar. "
                    "Demorou mais? Sem problema, a gravação pode acabar com o carro andando.",
                    "Antes da próxima etapa, pare em local seguro, em P, com o motor ligado, para apertar ENTER.",
                    "Resultado: logs\\coleta_*.jsonl."],
        comandos=[cli("collect", "--dll", dll, "--minutes", "11", "--fuel", fuel)],
        tempo="11 min",
    )
    return [
        preparo,
        erros_antes,
        trajeto,
        Etapa(
            titulo="Coleta guiada andando (OBD + LIDs + DIDs)",
            condicao=cond,
            instrucoes=["MELHOR com o carro FRIO (primeira partida do dia, sem aquecer antes): a subida da temperatura do "
                        "fluido do câmbio, gravada do começo ao fim, é o que permite achar o byte da temperatura no TCM.",
                        "Aperte ENTER ainda parado, em P; o roteiro dá o aviso do 1º passo.",
                        "Resultado: logs\\coleta_*.jsonl (com linhas 'estimulo')."],
            comandos=[cli("collect", "--dll", dll, "--estimulos", "andando", "--fuel", fuel)],
            tempo="~5 min",
            para_sozinho_em_s=seg,
        ),
        Etapa(
            titulo="Escuta do CAN guiada andando, mesma sequência",
            condicao=cond,
            instrucoes=["Repita o mesmo trecho, com o mesmo ritmo e as mesmas velocidades.",
                        "Resultado: logs\\sniff_*.jsonl (com linhas 'estimulo')."],
            comandos=[cli("sniff", "--dll", dll, "--estimulos", "andando", "--fuel", fuel)],
            tempo="~5 min",
            para_sozinho_em_s=seg,
        ),
        Etapa(
            titulo="Puxada controlada (só OBD, leitura rápida) — opcional",
            condicao=("SÓ em local seguro e permitido (pista fechada, estrada particular ou dinamômetro), motor aquecido "
                      "(>80 °C), via reta e livre. Em via pública não ultrapasse o limite: aperte ESC para pular esta etapa."),
            instrucoes=["Três puxadas de acelerador até o fundo (10 s cada), voltando a ~40 km/h entre elas, sem frear.",
                        "Lê só 11 PIDs do OBD (rotação, velocidade, carga, acelerador, MAF, avanço, correção de combustível, "
                        "lambda comandado, sonda), várias vezes por segundo, para o `analisar-log` ter carga plena.",
                        "Resultado: logs\\coleta_*.jsonl (com linhas 'estimulo')."],
            comandos=[cli("collect", "--dll", dll, "--estimulos", "puxada", "--so-obd",
                          "--pids", "0C,0D,04,11,10,0E,06,07,44,03,14", "--fuel", fuel)],
            tempo="~3 min",
            para_sozinho_em_s=int(duracao_total(PUXADA)) + 60,
        ),
        erros_depois,
    ]


def montar_etapas_erros(dll: str, fuel: str = "etanol") -> list[Etapa]:
    """Só lê os códigos de falha de motor, câmbio e demais módulos. Não apaga nada."""
    return [
        montar_etapas_coleta(dll, fuel)[0],
        Etapa(
            titulo="Ler códigos de falha (motor, câmbio, direção, painel, carroceria, IPDM)",
            condicao="Carro parado, motor ligado (ou só ignição ligada). Dashboard fechado: um programa por vez.",
            instrucoes=["Só leitura: não apaga nada.",
                        "No fim aparece a lista de códigos com descrição. Resposta 'sem resposta' NÃO quer dizer sem falhas.",
                        "Resultado: logs\\erros_*.txt (para ler) e logs\\erros_*.json (cru)."],
            comandos=[cli("ler-erros", "--dll", dll)],
            tempo="1 min",
        ),
    ]


ROTEIROS = {"completo": "montar_etapas", "proximo": "montar_etapas_proximo",
            "varredura": "montar_etapas_varredura", "pendentes": "montar_etapas_pendentes",
            "estrada": "montar_etapas_estrada", "coleta": "montar_etapas_coleta",
            "descoberta": "montar_etapas_descoberta", "gravacao": "montar_etapas_gravacao",
            "dids": "montar_etapas_dids", "guiado": "montar_etapas_guiado",
            "guiado_andando": "montar_etapas_guiado_andando",
            "erros": "montar_etapas_erros"}


# ------------------------------------------------------------------ teclado
def _limpar_teclas() -> None:
    if os.name == "nt":
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getwch()


def esperar_tecla(texto: str, permitidas: dict[str, str]) -> str:
    """Espera uma tecla de `permitidas` (tecla -> nome) e devolve o nome."""
    print(texto, end="", flush=True)
    if os.name != "nt":
        resp = input().strip().lower()
        return "pular" if resp in ("p", "esc") else "fazer"
    import msvcrt
    _limpar_teclas()
    while True:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):          # tecla especial (setas etc.)
            msvcrt.getwch()
            continue
        if ch == "\x03":
            raise KeyboardInterrupt
        nome = permitidas.get(ch) or permitidas.get(ch.lower())
        if nome:
            print()
            return nome


# ----------------------------------------------------------------- execução
def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    src = str(ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [src, env.get("PYTHONPATH")]))
    return env


def preparar(cmd: list[str]) -> list[str]:
    """Troca {agora} pela hora atual (nome de arquivo novo a cada execução)."""
    agora = _agora()
    return [c.replace("{agora}", agora) for c in cmd]


def rodar_e_salvar(cmd: list[str], nome: str) -> str:
    """Roda um comando curto, mostra a saída e grava uma cópia em logs/."""
    destino = LOGS / f"{nome}_{_agora()}.txt"
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, env=_env(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    saida = proc.stdout
    if proc.stderr:
        saida += "\n[stderr]\n" + proc.stderr
    print(saida)
    destino.write_text(saida, encoding="utf-8")
    return f"saiu com código {proc.returncode}; saída em {destino.name}"


def rodar_comando(cmd: list[str], para_sozinho_em_s: int | None) -> str:
    full = [sys.executable, *cmd]
    if para_sozinho_em_s is None:
        # Ctrl+C chega ao comando (que salva o que já leu); o roteiro ignora.
        anterior = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            rc = subprocess.call(full, cwd=ROOT, env=_env())
        finally:
            signal.signal(signal.SIGINT, anterior)
        return f"saiu com código {rc}"

    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    proc = subprocess.Popen(full, cwd=ROOT, env=_env(), creationflags=flags)
    motivo = "tempo esgotado"
    try:
        proc.wait(timeout=para_sozinho_em_s)
        return f"saiu com código {proc.returncode}"
    except subprocess.TimeoutExpired:
        pass
    except KeyboardInterrupt:
        motivo = "Ctrl+C"
    print(f"\n  Parando ({motivo})...")
    _parar(proc)
    return f"parado ({motivo})"


def _parar(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        proc.wait(timeout=15)
    except (subprocess.TimeoutExpired, OSError):
        proc.kill()
        proc.wait()


def verificar_ambiente(dll: str) -> list[str]:
    problemas = []
    bits = struct.calcsize("P") * 8
    if bits != 32:
        problemas.append(f"Python de {bits} bits. A DLL do GD101 precisa de 32 bits: "
                         "abra pelo roteiro.bat ou use .\\.venv\\Scripts\\python.exe roteiro_carro.py")
    if not Path(dll).exists():
        problemas.append(f"DLL não encontrada: {dll}")
    return problemas


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Roteiro guiado do teste no carro")
    ap.add_argument("--de", type=int, default=1, help="começar na etapa N")
    ap.add_argument("--listar", action="store_true", help="só listar etapas e comandos")
    ap.add_argument("--dll", default=DEFAULT_DLL)
    ap.add_argument("--fuel", default="etanol", help="combustível no tanque, registrado na coleta (roteiro coleta)")
    ap.add_argument("--roteiro", choices=sorted(ROTEIROS), default="completo",
                    help="completo = bateria inteira; proximo = só o que falta validar; "
                         "varredura = todos os IDs CAN, só leitura")
    args = ap.parse_args(argv)
    # Nunca quebrar no meio do teste por causa de acento num terminal antigo.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    montar = globals()[ROTEIROS[args.roteiro]]
    etapas = montar(args.dll, args.fuel) if args.roteiro in ("coleta", "gravacao", "guiado", "guiado_andando") else montar(args.dll)
    if args.listar:
        for i, e in enumerate(etapas, 1):
            print(f"\n{i:2d}. {e.titulo}  ({e.tempo})\n    {e.condicao}")
            for c in e.comandos:
                print("    python " + " ".join(c))
        return 0

    problemas = verificar_ambiente(args.dll)
    if problemas:
        print("\nNão dá para começar:")
        for p in problemas:
            print("  - " + p)
        return 1

    LOGS.mkdir(exist_ok=True)
    registro = LOGS / f"roteiro_{_agora()}.txt"

    def anotar(texto: str) -> None:
        linha = f"{dt.datetime.now().isoformat(timespec='seconds')}  {texto}"
        with registro.open("a", encoding="utf-8") as f:
            f.write(linha + "\n")

    anotar(f"início; Python {sys.version.split()[0]}; DLL {args.dll}")
    print("=" * 64)
    print("  ROTEIRO DO TESTE NO CARRO")
    print("  ENTER = fazer a etapa   ESC = pular   Ctrl+C = parar a etapa")
    print(f"  Registro: {registro}")
    print("=" * 64)

    total = len(etapas)

    def fazer_etapa(i: int, rodada: str = "") -> bool:
        """Mostra a etapa i. Devolve True se foi feita, False se foi pulada."""
        e = etapas[i - 1]
        print(f"\n{'-' * 64}\n{rodada}ETAPA {i} de {total}: {e.titulo}   (cerca de {e.tempo})")
        print(f"\n  ANTES: {e.condicao}")
        for linha in e.instrucoes:
            print(f"   • {linha}")
        escolha = esperar_tecla("\n  ENTER = fazer   ESC = pular  > ",
                                {**{k: "fazer" for k in ENTER_KEYS}, ESC_KEY: "pular"})
        if escolha == "pular":
            print("  Pulada. Ela volta a aparecer no final.")
            anotar(f"etapa {i} PULADA: {e.titulo}")
            return False
        while True:
            anotar(f"etapa {i} INÍCIO: {e.titulo}")
            for linha in e.durante:
                print(f"\n  >>> {linha} <<<")
            resultados = []
            for n, modelo in enumerate(e.comandos):
                if e.pedir_antes:
                    print(f"\n  >>> {e.pedir_antes[n]} <<<")
                    pronto = esperar_tecla("  ENTER quando estiver pronto   ESC = pular esta leitura  > ",
                                           {**{k: "pronto" for k in ENTER_KEYS}, ESC_KEY: "pular"})
                    if pronto == "pular":
                        resultados.append("leitura pulada")
                        anotar(f"etapa {i} leitura {n + 1} PULADA: {e.pedir_antes[n]}")
                        continue
                cmd = preparar(modelo)
                print(f"\n  rodando: python {' '.join(cmd)}\n")
                if e.salvar_saida_como:
                    resultados.append(rodar_e_salvar(cmd, e.salvar_saida_como[n]))
                else:
                    resultados.append(rodar_comando(cmd, e.para_sozinho_em_s))
                anotar(f"etapa {i} comando: {' '.join(cmd)} -> {resultados[-1]}")
            print(f"\n  Etapa {i} terminou: {'; '.join(resultados)}")
            escolha = esperar_tecla("  ENTER = próxima etapa   R = repetir esta  > ",
                                    {**{k: "seguir" for k in ENTER_KEYS}, "r": "repetir"})
            if escolha != "repetir":
                return True
            anotar(f"etapa {i} REPETIR")

    feitas: list[int] = []
    puladas: list[int] = []
    try:
        for i in range(max(1, args.de), total + 1):
            (feitas if fazer_etapa(i) else puladas).append(i)

        while puladas:
            print(f"\n{'=' * 64}\n  Ficaram {len(puladas)} etapa(s) pulada(s):")
            for i in puladas:
                print(f"   {i:2d}. {etapas[i - 1].titulo}")
            escolha = esperar_tecla(
                "\n  ENTER = tentar as puladas agora   ESC = terminar sem elas  > ",
                {**{k: "voltar" for k in ENTER_KEYS}, ESC_KEY: "terminar"},
            )
            if escolha == "terminar":
                break
            anotar(f"voltando às puladas: {puladas}")
            ainda = []
            for i in puladas:
                (feitas if fazer_etapa(i, rodada="(PULADA) ") else ainda).append(i)
            puladas = ainda
    except KeyboardInterrupt:
        print("\n\nRoteiro interrompido.")
        anotar(f"roteiro interrompido; feitas {sorted(feitas)}; puladas {puladas}")
        return 130

    anotar(f"fim; feitas {sorted(feitas)}; não feitas {puladas}")
    print(f"\n{'=' * 64}\n  FIM. Pode desligar o carro.")
    print(f"  Feitas: {len(feitas)} de {total - max(1, args.de) + 1}.")
    if puladas:
        print("  Ficaram sem fazer:")
        for i in puladas:
            print(f"   {i:2d}. {etapas[i - 1].titulo}")
        print(f"  Para fazer depois: python roteiro_carro.py --de N")
    print(f"  Os arquivos ficaram em logs\\ (registro: {registro.name}).\n{'=' * 64}")
    return 0

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002


@contextmanager
def manter_acordado(kernel32=None):
    """Impede o Windows de suspender ou apagar a tela enquanto o roteiro roda.

    Sem isso, uma captura de 15-20 min pode parar no meio porque o notebook
    dormiu. Usa SetThreadExecutionState; vale só enquanto este processo
    estiver aberto e é desfeito ao sair. Em outro sistema não faz nada.
    """
    if kernel32 is None and os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
    ativo = False
    if kernel32 is not None:
        try:
            ativo = bool(kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED))
        except Exception:  # noqa: BLE001 — nunca impedir o roteiro de rodar
            ativo = False
    if not ativo and os.name == "nt":
        print("AVISO: não consegui impedir a suspensão do Windows. "
              "Deixe o notebook na tomada e desative a suspensão nas configurações.")
    try:
        yield ativo
    finally:
        if ativo:
            try:
                kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    with manter_acordado():
        sys.exit(main())
