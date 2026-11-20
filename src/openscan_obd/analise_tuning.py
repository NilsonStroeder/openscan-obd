"""Análise offline de logs de coleta (OBD modo 01) no estilo de quem prepara motor: correção de combustível,
avanço, MAF, malha aberta/fechada, puxadas e tempos de aceleração.

Só lê arquivos `coleta_*.jsonl`; não fala com o carro. Fórmulas SAE J1979. Sonda de banda larga (PID 0x24)
e detonação não fazem parte do que este carro entrega pelo OBD; o relatório avisa quando isso limita a leitura.
"""
from __future__ import annotations

import bisect
import json
import statistics
from collections import defaultdict
from pathlib import Path

JANELA_JUNCAO_S = 2.0       # distância máxima entre a leitura de RPM e a de outro PID para valerem como uma amostra
STATUS_COMBUSTIVEL = {1: "malha aberta (motor frio)", 2: "malha fechada", 4: "malha aberta (carga/desaceleração)",
                      8: "malha aberta (falha)", 16: "malha fechada (falha na sonda)"}


def _u16(b: bytes) -> int:
    return b[2] * 256 + b[3]


DECODIFICADORES = {
    0x03: ("fuel_status", lambda b: b[2]),
    0x04: ("load", lambda b: b[2] * 100 / 255),
    0x05: ("ect", lambda b: b[2] - 40),
    0x06: ("stft", lambda b: (b[2] - 128) * 100 / 128),
    0x07: ("ltft", lambda b: (b[2] - 128) * 100 / 128),
    0x0C: ("rpm", lambda b: _u16(b) / 4),
    0x0D: ("speed", lambda b: b[2]),
    0x0E: ("timing", lambda b: b[2] / 2 - 64),
    0x0F: ("iat", lambda b: b[2] - 40),
    0x10: ("maf", lambda b: _u16(b) / 100),
    0x11: ("thr", lambda b: b[2] * 100 / 255),
    0x14: ("o2_b1s1", lambda b: b[2] / 200),
    0x15: ("o2_b1s2", lambda b: b[2] / 200),
    0x42: ("volt", lambda b: _u16(b) / 1000),
    0x43: ("abs_load", lambda b: _u16(b) * 100 / 255),
    0x44: ("lam_cmd", lambda b: _u16(b) / 32768),
}
TAMANHO_MIN = {0x0C: 4, 0x10: 4, 0x42: 4, 0x43: 4, 0x44: 4}


def carregar_obd(paths: list[Path]) -> dict[int, list[tuple[float, bytes]]]:
    """PID -> [(t, resposta)] só com respostas positivas do modo 01 (0x41); ignora NRC, timeout e modos de DTC."""
    serie: dict[int, list[tuple[float, bytes]]] = defaultdict(list)
    for path in paths:
        for linha in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if not str(r.get("src", "")).startswith("obd:") or "raw" not in r:
                continue
            b = bytes.fromhex(r["raw"])
            if len(b) < 3 or b[0] != 0x41:
                continue
            serie[b[1]].append((float(r["t"]), b))
    for v in serie.values():
        v.sort(key=lambda x: x[0])
    return dict(serie)


def amostras(serie: dict[int, list[tuple[float, bytes]]]) -> list[dict]:
    """Junta, a cada leitura de RPM, a leitura mais próxima (até 2 s) de cada outro PID."""
    ancoras = serie.get(0x0C, [])
    tempos = {pid: [t for t, _ in v] for pid, v in serie.items()}
    saida = []
    for t, b in ancoras:
        if len(b) < TAMANHO_MIN[0x0C]:
            continue
        a = {"t": t, "rpm": _u16(b) / 4}
        for pid, (campo, f) in DECODIFICADORES.items():
            if pid == 0x0C or pid not in serie:
                continue
            ts = tempos[pid]
            i = bisect.bisect_left(ts, t)
            melhor = min((j for j in (i - 1, i) if 0 <= j < len(ts)), key=lambda j: abs(ts[j] - t), default=None)
            if melhor is None or abs(ts[melhor] - t) > JANELA_JUNCAO_S:
                continue
            resp = serie[pid][melhor][1]
            if len(resp) < TAMANHO_MIN.get(pid, 3):
                continue
            a[campo] = f(resp)
        if "stft" in a and "ltft" in a:
            a["trim"] = a["stft"] + a["ltft"]
        saida.append(a)
    return saida


def mapa(am: list[dict], campo: str, rpm_step: int = 500, carga_step: int = 20, min_n: int = 3) -> dict:
    """Média de `campo` por faixa de RPM × carga calculada; só células com pelo menos `min_n` amostras."""
    acum: dict[tuple[int, int], list[float]] = defaultdict(list)
    for a in am:
        if campo in a and "load" in a:
            acum[(int(a["rpm"] // rpm_step) * rpm_step, int(a["load"] // carga_step) * carga_step)].append(a[campo])
    celulas = {k: {"media": statistics.fmean(v), "n": len(v), "min": min(v), "max": max(v)}
               for k, v in acum.items() if len(v) >= min_n}
    return {"campo": campo, "rpm_step": rpm_step, "carga_step": carga_step, "celulas": celulas}


def puxadas(am: list[dict], thr_min: float = 70, min_amostras: int = 3, lacuna_s: float = 3.0) -> list[dict]:
    """Trechos seguidos com acelerador ≥ thr_min (candidatos a puxada de carga plena)."""
    saida, atual = [], []

    def fecha() -> None:
        if len(atual) >= min_amostras:
            g = lambda c: [a[c] for a in atual if c in a]  # noqa: E731
            saida.append({
                "t0": atual[0]["t"], "n": len(atual), "duracao_s": atual[-1]["t"] - atual[0]["t"],
                "rpm_min": min(g("rpm")), "rpm_max": max(g("rpm")),
                "speed_min": min(g("speed"), default=None), "speed_max": max(g("speed"), default=None),
                "maf_max": max(g("maf"), default=None),
                "timing_min": min(g("timing"), default=None), "timing_max": max(g("timing"), default=None),
                "lam_cmd_max": max(g("lam_cmd"), default=None), "thr_max": max(g("thr"), default=None),
                "trim_medio": statistics.fmean(g("trim")) if g("trim") else None,
            })
        atual.clear()

    for a in am:
        if a.get("thr", 0) >= thr_min and (not atual or a["t"] - atual[-1]["t"] <= lacuna_s):
            atual.append(a)
        else:
            fecha()
            if a.get("thr", 0) >= thr_min:
                atual.append(a)
    fecha()
    return saida


def tempo_aceleracao(am: list[dict], de: float, ate: float, tolerancia: float = 3.0, lacuna_s: float = 3.0) -> float | None:
    """Menor tempo (s) para ir de `de` a `ate` km/h sem a velocidade cair mais que a tolerância; None se nunca ocorreu."""
    melhor = None
    t_ini = None
    ant = None
    for a in am:
        v = a.get("speed")
        if v is None:
            continue
        if ant is not None and a["t"] - ant["t"] > lacuna_s:
            t_ini = None
        if ant is not None:
            if t_ini is None and ant["speed"] < de <= v:
                dv = v - ant["speed"]
                t_ini = ant["t"] + (de - ant["speed"]) / dv * (a["t"] - ant["t"])
            elif t_ini is not None and v < ant["speed"] - tolerancia:
                t_ini = None
            if t_ini is not None and ant["speed"] < ate <= v:
                dv = v - ant["speed"]
                t_fim = ant["t"] + (ate - ant["speed"]) / dv * (a["t"] - ant["t"])
                if melhor is None or t_fim - t_ini < melhor:
                    melhor = t_fim - t_ini
                t_ini = None
        ant = a
    return melhor


def _est(v: list[float]) -> str:
    return f"média {statistics.fmean(v):.1f}, mín {min(v):.1f}, máx {max(v):.1f}" if v else "sem dados"


def _tabela(m: dict, unidade: str = "", casas: int = 1) -> list[str]:
    cel = m["celulas"]
    if not cel:
        return ["_Sem células com amostras suficientes._", ""]
    rpms = sorted({k[0] for k in cel})
    cargas = sorted({k[1] for k in cel})
    cab = "| RPM \\ carga % | " + " | ".join(f"{c}–{c + m['carga_step']}" for c in cargas) + " |"
    linhas = [cab, "|" + "---|" * (len(cargas) + 1)]
    for r in rpms:
        cols = []
        for c in cargas:
            v = cel.get((r, c))
            cols.append(f"{v['media']:.{casas}f}{unidade} ({v['n']})" if v else "·")
        linhas.append(f"| {r}–{r + m['rpm_step']} | " + " | ".join(cols) + " |")
    return linhas + [""]


def relatorio(am: list[dict], arquivos: list[str]) -> str:
    if not am:
        return "# Análise de log\n\nSem amostras de OBD (nenhum PID 0C encontrado nos arquivos).\n"
    g = lambda c: [a[c] for a in am if c in a]  # noqa: E731
    dur = am[-1]["t"] - am[0]["t"]
    L = ["# Análise de log para calibração", "",
         f"Arquivos: {', '.join(arquivos) or '—'}", f"Amostras: {len(am)} (RPM como âncora), intervalo {dur / 60:.1f} min.", ""]
    L += ["## Faixa de uso", "", "| Grandeza | Faixa |", "|---|---|"]
    for nome, c, un in [("RPM", "rpm", ""), ("Velocidade", "speed", " km/h"), ("Carga calculada", "load", " %"),
                        ("Acelerador", "thr", " %"), ("MAF", "maf", " g/s"), ("Temp. líquido", "ect", " °C"),
                        ("Temp. ar admissão", "iat", " °C"), ("Tensão", "volt", " V")]:
        v = g(c)
        if v:
            L.append(f"| {nome} | {min(v):.0f}–{max(v):.0f}{un} |" if c not in ("maf", "volt") else f"| {nome} | {min(v):.1f}–{max(v):.1f}{un} |")
    L.append("")
    st = g("fuel_status")
    if st:
        L += ["## Malha de combustível", ""]
        cont = defaultdict(int)
        for s in st:
            cont[int(s)] += 1
        for k, n in sorted(cont.items(), key=lambda x: -x[1]):
            L.append(f"- {STATUS_COMBUSTIVEL.get(k, f'código {k}')}: {n / len(st) * 100:.0f}% das amostras")
        L.append("")
    L += ["## Correção de combustível", ""]
    for nome, c in [("STFT (curto prazo)", "stft"), ("LTFT (longo prazo)", "ltft"), ("Correção total (STFT+LTFT)", "trim")]:
        L.append(f"- {nome}: {_est(g(c))} %")
    L += ["", "Mapa da correção total (média %, amostras entre parênteses):", ""]
    L += _tabela(mapa(am, "trim"), "%")
    L += ["## Avanço de ignição", "", f"Geral: {_est(g('timing'))} °", ""]
    L += _tabela(mapa(am, "timing"), "°")
    L += ["## MAF por faixa de RPM", ""]
    maf = mapa(am, "maf", carga_step=100, min_n=2)
    for (r, _), v in sorted(maf["celulas"].items()):
        L.append(f"- {r}–{r + 500} rpm: {v['media']:.1f} g/s (máx {v['max']:.1f}, {v['n']} amostras)")
    L.append("")
    lam = g("lam_cmd")
    if lam:
        L += ["## Lambda comandado e sondas", "",
              f"- Equivalência comandada (PID 44): {_est(lam)} (1,00 = mistura estequiométrica)",
              f"- Sonda estreita antes do catalisador (tensão): {_est(g('o2_b1s1'))} V",
              f"- Sonda depois do catalisador: {_est(g('o2_b1s2'))} V", ""]
    obs = []
    lt = g("ltft")
    if lt and statistics.fmean(lt) >= 15:
        obs.append(f"LTFT médio alto (+{statistics.fmean(lt):.1f}%) e estável: pode vir do combustível (etanol), de ar falso ou do MAF; "
                   "só se separa comparando com um tanque de gasolina.")
    if lam and sum(x > 1.5 for x in lam) > 0:
        obs.append(f"Equivalência comandada saturada (>1,5) em {sum(x > 1.5 for x in lam) / len(lam) * 100:.0f}% das amostras: "
                   "provável corte de combustível na desaceleração (a confirmar).")
    if obs:
        L += ["## Observações", ""] + [f"- {o}" for o in obs] + [""]
    L += ["## Puxadas e acelerações", ""]
    p = puxadas(am)
    thr_max = max(g("thr"), default=0)
    if not p:
        L.append(f"Sem puxada de carga plena: acelerador máximo registrado: {thr_max:.0f}%.")
    for x in p:
        L.append(f"- Puxada de {x['duracao_s']:.1f} s: {x['rpm_min']:.0f}→{x['rpm_max']:.0f} rpm, "
                 f"{x['speed_min']:.0f}→{x['speed_max']:.0f} km/h, avanço {x['timing_min']:.0f}–{x['timing_max']:.0f}°, "
                 f"lambda comandado máx {x['lam_cmd_max']:.2f}, correção média {x['trim_medio']:+.1f}%")
    achou = False
    for de, ate in [(0, 100), (0, 60), (30, 60), (40, 80), (60, 100)]:
        t = tempo_aceleracao(am, de, ate)
        if t is not None:
            achou = True
            L.append(f"- {de}→{ate} km/h em {t:.1f} s (melhor trecho do log)")
    if not achou:
        L.append("- Sem trecho contínuo para medir 0→100, 30→60, 40→80 ou 60→100 km/h (a amostragem é de poucos segundos).")
    L += ["", "## Limites desta leitura", ""]
    if not p:
        L.append("- Sem puxada, não há dado de carga plena; o relatório cobre uso leve a moderado.")
    L += ["- Só sonda estreita: o PID 0x24 (sonda de banda larga) não é entregue por este carro; a mistura em carga alta "
          "não pode ser lida diretamente, só o lambda que a ECU comanda.",
          "- O OBD não traz detonação (knock) nem temperatura de escape.",
          "- Cadência de ~4,7 s por ciclo na gravação ampla: bom para tendências, ruim para transientes curtos."]
    return "\n".join(L) + "\n"


# ---- seções extras (LIDs do TCM e leitura de códigos) ----------------------------------------------------------

# Índices na resposta crua do TCM ("61 01 ..."), que é o payload do decoder do dashboard + 1 byte (SID).
# Byte 64 = 1 com o overdrive desligado (O/D OFF) e 0 com ele ligado (20/11/2026; hipótese medida num único trecho).
# Byte 31 (= b[30] do decoder do dashboard): contagem do ATF, convertida em °C pela tabela do ESM (estimada).
TCM_OD_BYTE = 64
TCM_TEMP_CONTAGEM_BYTE = 31


def carregar_kwp_byte(paths: list[Path], src: str, indice: int) -> list[tuple[float, int]]:
    """[(t, byte)] de uma fonte KWP (ex.: 'kwp:tcm_cvt:01'), ordenado no tempo."""
    out: list[tuple[float, int]] = []
    for path in paths:
        for linha in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(linha)
            except ValueError:
                continue
            if r.get("src") != src or "raw" not in r:
                continue
            b = bytes.fromhex(r["raw"])
            if len(b) > indice:
                out.append((float(r["t"]), b[indice]))
    out.sort(key=lambda x: x[0])
    return out


def _mais_proximo(serie: list[tuple[float, int]], t: float, tol: float = 4.0) -> int | None:
    ts = [x[0] for x in serie]
    i = bisect.bisect_left(ts, t)
    j = min((k for k in (i - 1, i) if 0 <= k < len(ts)), key=lambda k: abs(ts[k] - t), default=None)
    return serie[j][1] if j is not None and abs(ts[j] - t) <= tol else None


def secao_overdrive(am: list[dict], od: list[tuple[float, int]], vmin: float = 30.0) -> list[str]:
    """Rotação por km/h com o overdrive ligado e desligado (só amostras acima de vmin km/h)."""
    L = ["## Overdrive (O/D OFF)", ""]
    if not od:
        return L + ["Sem leitura do LID 01 do TCM nestes arquivos (use a gravação ampla, não a só-OBD).", ""]
    grupos: dict[bool, list[tuple[float, float]]] = {True: [], False: []}
    for a in am:
        if a.get("speed", 0) < vmin:
            continue
        v = _mais_proximo(od, a["t"])
        if v is not None:
            grupos[v == 1].append((a["speed"], a["rpm"] / a["speed"]))
    if not grupos[True]:
        return L + [f"O/D OFF não apareceu acima de {vmin:.0f} km/h nestes arquivos.", ""]
    vel_off = statistics.median(s for s, _ in grupos[True])
    off = statistics.median(r for _, r in grupos[True])
    L.append(f"- Com O/D OFF: {off:.0f} rpm por km/h (mediana, {len(grupos[True])} amostras, ~{vel_off:.0f} km/h)")
    perto = [r for s, r in grupos[False] if abs(s - vel_off) <= 10]
    if perto:
        on = statistics.median(perto)
        L.append(f"- Com O/D ligado na mesma faixa de velocidade (±10 km/h): {on:.0f} rpm por km/h "
                 f"({len(perto)} amostras): O/D OFF gira {off / on:.1f}x mais")
    L += ["- Detecção pelo byte 64 do LID 01 do TCM (hipótese medida num único trecho de 20 s).", ""]
    return L


def secao_temperatura_fluido(serie: list[tuple[float, int]]) -> list[str]:
    """Contagem do ATF (byte 31 do 61 01) convertida pela mesma tabela do dashboard. ESTIMADA, sem referência externa."""
    from openscan_obd.gateway.tcm_lid01 import atf_temp_c

    L = ["## Temperatura do fluido do CVT (estimada)", ""]
    if len(serie) < 5:
        return L + ["Sem leitura do LID 01 do TCM nestes arquivos.", ""]
    ini, fim = serie[0][1], serie[-1][1]
    minutos = (serie[-1][0] - serie[0][0]) / 60
    L += [f"- Contagem do ATF: {ini} no início, {fim} no fim ({minutos:.0f} min); máx {max(v for _, v in serie)}.",
          f"- Pela tabela do ESM (a mesma do dashboard): {atf_temp_c(ini):.0f} °C no início, {atf_temp_c(fim):.0f} °C no fim; "
          f"máx {atf_temp_c(max(v for _, v in serie)):.0f} °C.",
          "- ESTIMADA: não temos referência independente (termômetro ou Consult) para confirmar a tabela.", ""]
    return L


def secao_partida_a_frio(paths: list[Path], janela_s: float = 60.0, limite_c: float = 6.0) -> list[str]:
    """Primeira leitura de cada arquivo: se o carro estava frio (líquido ~ ar), compara fluido, líquido e ar.

    Depois de uma noite parado, fluido, líquido de arrefecimento e ar admissão ficam na mesma temperatura. Se a
    tabela do ESM estiver certa, o fluido estimado deve cair perto dos outros dois. É a checagem que dispensa
    termômetro externo."""
    from openscan_obd.gateway.tcm_lid01 import atf_temp_c

    L = ["## Partida a frio: fluido x líquido x ar", ""]
    achou = False
    for path in paths:
        obd = carregar_obd([Path(path)])
        atf = carregar_kwp_byte([Path(path)], "kwp:tcm_cvt:01", TCM_TEMP_CONTAGEM_BYTE)
        if not atf or 0x05 not in obd or 0x0F not in obd:
            continue
        t0 = atf[0][0]
        ect = next((b[2] - 40 for t, b in obd[0x05] if t >= t0 - 2 and len(b) > 2), None)
        iat = next((b[2] - 40 for t, b in obd[0x0F] if t >= t0 - 2 and len(b) > 2), None)
        if ect is None or iat is None or atf[0][0] - t0 > janela_s:
            continue
        fluido = atf_temp_c(atf[0][1])
        nome = Path(path).name
        if abs(ect - iat) > limite_c:
            L.append(f"- {nome}: carro NÃO estava frio (líquido {ect} °C, ar {iat} °C): sem comparação.")
            continue
        achou = True
        d_ect, d_iat = fluido - ect, fluido - iat
        veredito = ("compatível com a tabela" if max(abs(d_ect), abs(d_iat)) <= 6
                    else "diferença grande: desconfiar da tabela ou de que o carro não estava frio de verdade")
        L.append(f"- {nome}: fluido estimado {fluido:.0f} °C, líquido {ect} °C, ar {iat} °C "
                 f"(fluido-líquido {d_ect:+.0f}, fluido-ar {d_iat:+.0f}): {veredito}.")
    if not achou and len(L) == 2:
        L.append("Nenhuma partida a frio nestes arquivos (grave a primeira partida do dia: ignição ligada, motor desligado, "
                 "ou a coleta logo após ligar).")
    L.append("")
    return L


def secao_erros(arquivos: list[Path]) -> list[str]:
    """Resumo dos erros_*.json (leitura de códigos de falha); compara o primeiro com o último."""
    L = ["## Códigos de falha lidos", ""]
    if not arquivos:
        return L + ["Nenhum erros_*.json na pasta (rode ler_erros.bat).", ""]
    leituras = []
    for p in sorted(arquivos):
        try:
            d = json.loads(Path(p).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cods: dict[str, set[str]] = {}
        for m in d.get("modulos", []):
            if "modos" in m:
                s = {c for e in m["modos"].values() for c in e.get("codigos", [])}
            else:
                s = {c["code"] for c in (m.get("decodificado") or {}).get("codes", [])}
            cods[m["modulo"]] = s
        leituras.append((Path(p).name, cods))
    for nome, cods in leituras:
        total = sorted(c for s in cods.values() for c in s)
        L.append(f"- {nome}: {', '.join(total) if total else 'nenhum código'}")
    if len(leituras) >= 2:
        novos = [(m, sorted(s - leituras[0][1].get(m, set()))) for m, s in leituras[-1][1].items()]
        novos = [(m, n) for m, n in novos if n]
        L.append("- Códigos novos na última leitura em relação à primeira: " +
                 ("; ".join(f"{m}: {', '.join(n)}" for m, n in novos) if novos else "nenhum"))
    L.append("")
    return L


def relatorio_completo(paths: list[Path], erros: list[Path]) -> str:
    am = amostras(carregar_obd(paths))
    texto = relatorio(am, [p.name for p in paths]).rstrip("\n").split("\n")
    extra = (secao_overdrive(am, carregar_kwp_byte(paths, "kwp:tcm_cvt:01", TCM_OD_BYTE))
             + secao_temperatura_fluido(carregar_kwp_byte(paths, "kwp:tcm_cvt:01", TCM_TEMP_CONTAGEM_BYTE))
             + secao_partida_a_frio(paths)
             + secao_erros(erros))
    # as seções extras entram antes de "Limites desta leitura", que continua por último
    try:
        i = texto.index("## Limites desta leitura")
    except ValueError:
        i = len(texto)
    return "\n".join(texto[:i] + extra + texto[i:]) + "\n"
