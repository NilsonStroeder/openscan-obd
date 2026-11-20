"""Leitura de códigos de falha (DTC) de todos os módulos que respondem. SÓ LEITURA: não apaga nada.

ECM (motor): OBD-II 03 (armazenados), 07 (pendentes) e 0A (permanentes).
TCM (câmbio CVT) e demais módulos Nissan: KWP 10 C0 + 17 FF 00. Em 16/11/2026 o TCM respondeu assim e um dos
códigos (P1722) bateu com a ferramenta da loja. O byte de status continua sem significado conhecido: é mostrado cru.
Resposta vazia (57 00) é uma resposta válida de "0 códigos"; ausência de resposta NÃO quer dizer sem falhas.
"""
from __future__ import annotations

import time
from typing import Callable

from openscan_obd.gateway.kwp_dtc17 import decode_status_of_dtc
from openscan_obd.gateway.scan import _set, probe
from openscan_obd.obd2 import decode_dtc_response

ECM = (0x7E0, 0x7E8)
MODULOS_KWP = (
    ("Câmbio CVT (TCM)", 0x7E1, 0x7E9),
    ("Direção elétrica (EPS)", 0x742, 0x762),
    ("Painel (meter)", 0x743, 0x763),
    ("Carroceria (BCM)", 0x745, 0x765),
    ("IPDM (fusíveis/relés)", 0x74D, 0x76D),
)

# Descrições do manual de serviço Nissan do CVT (JF011E/RE0F10A) e do OBD-II genérico.
NOMES = {
    "P0703": "Circuito do interruptor do pedal de freio",
    "P0705": "Circuito do sensor de posição P/N (PNP)",
    "P0710": "Sensor de temperatura do fluido do CVT",
    "P0715": "Sensor de velocidade de entrada (primária)",
    "P0720": "Sensor de velocidade de saída",
    "P0725": "Sinal de rotação do motor",
    "P0730": "Dano na correia (relação incorreta)",
    "P0740": "Circuito do solenoide do conversor de torque (TCC)",
    "P0744": "Função do solenoide do conversor de torque",
    "P0745": "Circuito do solenoide de pressão de linha",
    "P0746": "Função do solenoide de controle de pressão A",
    "P0776": "Função do solenoide de controle de pressão B",
    "P0778": "Circuito do solenoide de controle de pressão B",
    "P0826": "Interruptor do modo manual",
    "P0840": "Circuito do sensor de pressão do fluido A",
    "P0841": "Função do sensor de pressão do fluido",
    "P0868": "Queda da pressão secundária",
    "P1701": "Fonte de alimentação do TCM",
    "P1705": "Sinal do sensor de posição da borboleta",
    "P1722": "Sinal de velocidade do veículo (ABS/ESTM, via CAN)",
    "P1723": "Função do sensor de velocidade do CVT",
    "P1726": "Controle eletrônico da borboleta",
    "P1740": "Circuito do solenoide de travamento/seleção",
    "P1745": "Controle de pressão de linha",
    "P1777": "Circuito do motor de passo",
    "P1778": "Função do motor de passo",
    "U1000": "Circuito de comunicação CAN",
    "U1010": "Unidade de controle do câmbio (CAN)",
}


def _nome(code: str) -> str:
    return NOMES.get(code, "(sem descrição na tabela; ver manual de serviço)")


def _ler_ecm(device) -> dict:
    _set(device, *ECM)
    out: dict = {"modulo": "Motor (ECM)", "metodo": "OBD-II modos 03, 07, 0A", "modos": {}}
    for mode, nome in ((0x03, "armazenados"), (0x07, "pendentes"), (0x0A, "permanentes")):
        r = probe(device, bytes([mode]), timeout_ms=500)
        entry: dict = {"status": r["status"], "raw": r.get("response", "")}
        if r["status"] == "ok":
            try:
                entry["codigos"] = decode_dtc_response(bytes.fromhex(r["response"]), mode)
            except ValueError as exc:
                entry["status"] = "decode_error"
                entry["erro"] = str(exc)
        elif r["status"] == "nrc":
            entry["nrc"] = r.get("nrc")
        out["modos"][nome] = entry
    return out


def _ler_kwp(device, nome: str, tx: int, rx: int) -> dict:
    out: dict = {"modulo": nome, "metodo": "KWP 10 C0 + 17 FF 00", "ids": f"{tx:03X}/{rx:03X}"}
    if not _set(device, tx, rx):
        return {**out, "status": "pulado", "motivo": "adaptador sem troca de IDs"}
    sessao = probe(device, b"\x10\xc0")
    out["sessao"] = sessao["status"]
    r = probe(device, b"\x17\xff\x00", timeout_ms=500)
    out["status"] = r["status"]
    if "response" in r:
        out["raw"] = r["response"]
    if r["status"] == "nrc":
        out["nrc"] = r.get("nrc")
    if r["status"] == "ok":
        try:
            out["decodificado"] = decode_status_of_dtc(bytes.fromhex(r["response"]))
        except ValueError as exc:
            out["status"] = "decode_error"
            out["erro"] = str(exc)
    return out


def ler_erros(device, progress: Callable[[str], None] | None = None) -> dict:
    tick = progress or (lambda _s: None)
    result: dict = {"ts": time.time(), "somente_leitura": True, "modulos": []}
    try:
        tick("Motor (ECM)")
        result["modulos"].append(_ler_ecm(device))
        for nome, tx, rx in MODULOS_KWP:
            tick(nome)
            result["modulos"].append(_ler_kwp(device, nome, tx, rx))
    finally:
        _set(device, *ECM)
    return result


def formatar(result: dict) -> str:
    linhas = ["LEITURA DE CÓDIGOS DE FALHA (somente leitura; nada foi apagado)", ""]
    for m in result["modulos"]:
        linhas.append(f"== {m['modulo']} ({m['metodo']})")
        if "modos" in m:
            for nome, e in m["modos"].items():
                if e["status"] == "ok":
                    cods = e.get("codigos", [])
                    if cods:
                        linhas.append(f"  {nome}: {len(cods)} código(s)")
                        linhas += [f"    {c}  {_nome(c)}" for c in cods]
                    else:
                        linhas.append(f"  {nome}: respondeu 0 códigos")
                elif e["status"] == "nrc":
                    linhas.append(f"  {nome}: módulo recusou (NRC {e.get('nrc')})")
                else:
                    linhas.append(f"  {nome}: sem resposta utilizável ({e['status']})")
        else:
            st = m["status"]
            if st == "ok":
                d = m["decodificado"]
                if d["count"] == 0:
                    linhas.append("  respondeu 0 códigos")
                else:
                    linhas.append(f"  {d['count']} código(s):")
                    for c in d["codes"]:
                        linhas.append(f"    {c['code']}  {_nome(c['code'])}   [status cru {c['status_byte']}]")
            elif st == "nrc":
                linhas.append(f"  módulo recusou este pedido (NRC {m.get('nrc')}): leitura não disponível aqui")
            elif st == "pulado":
                linhas.append(f"  pulado: {m['motivo']}")
            else:
                linhas.append(f"  sem resposta utilizável ({st}): isso NÃO quer dizer sem falhas")
        linhas.append("")
    linhas.append("Observação: o byte de status ainda não tem significado conhecido; códigos P17xx da Nissan "
                  "não acendem a luz do motor.")
    return "\n".join(linhas)
