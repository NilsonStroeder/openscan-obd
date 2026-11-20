"""Análise pós-teste de campo dos logs do LID 0x01 do TCM CVT.

Uso:
    python analisar_logs.py [--desde YYYYMMDD_HHMMSS] [--logs DIR] [--out FILE.md]

Lê os logs de ``logs/`` (ou ``--logs``), carrega todo payload do LID 0x01 do
TCM (KWP 0x21, 69 bytes com o eco do LID em [0] e 0x5F em [68]) e grava um
relatório Markdown com as mesmas seções sempre, para que os achados saiam do
mesmo jeito a cada teste. Nunca sobrescreve um arquivo existente.

Escopo: veículo de teste Nissan Sentra B16 2010 (CVT JF011E), TCM 0x7E1/0x7E9,
adaptador GODIAG GD101. Nada aqui vale para outros veículos sem nova evidência.
Tudo que não está marcado como confirmado é hipótese NÃO VERIFICADA; os bytes
crus continuam nos logs de origem.

Só biblioteca padrão. Cada análise é uma função pura (lista de amostras ->
dict); ``main()`` só faz I/O.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import re
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

LID01_LEN = 69
END_MARKER = 0x5F
STATIC_ZERO_BYTES = (1, 2, 8, 29)
OBD_SIGNALS = ("RPM", "VSP", "TPS", "ECT")
R_REGRESSION_LIMIT = 0.95
SCAN_R_LIMIT = 0.8
SCAN_MIN_N = 10
HEX_KEYS = ("hex", "raw_hex", "lid01_hex", "payload_hex")

# Hipótese NÃO VERIFICADA (auditoria 2026-11-05): nibble alto de [54] = seletor.
SELECTOR_NIBBLE = {"P": 0x1, "N": 0x4, "D": 0x8, "R": 0x2}

# Faixas de velocidade OBD (km/h) para contar [38].
SPEED_BANDS = ((0, 0, "0"), (1, 20, "1-20"), (21, 50, "21-50"),
               (51, 80, "51-80"), (81, 100, "81-100"), (101, 999, ">100"))

TS_RE = re.compile(r"(\d{8}_\d{6})")
DESDE_RE = re.compile(r"^\d{8}_\d{6}$")


@dataclass
class Sample:
    """Um payload do LID 0x01 e o contexto de onde veio."""

    source: str
    kind: str                      # correlated | reverse | field_test | snapshot
    label: str
    payload: bytes
    index: int = 0
    t: float | None = None
    obd: dict[str, float | None] = field(default_factory=dict)
    times: dict[str, float | None] = field(default_factory=dict)   # tcm, RPM, VSP...


@dataclass
class FileResult:
    name: str
    kind: str
    samples: list[Sample]
    records: int = 0               # registros no arquivo (com ou sem payload)
    note: str = ""


# ---------------------------------------------------------------- utilidades
def file_timestamp(name: str) -> str | None:
    m = TS_RE.search(name)
    return m.group(1) if m else None


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson r, ou None se n < 2, se uma série for constante ou inválida."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        r = statistics.correlation(xs, ys)
    except (statistics.StatisticsError, ZeroDivisionError, ValueError):
        return None
    return None if math.isnan(r) else r


def percentile(values: list[float], p: float) -> float | None:
    """Percentil por posição mais próxima (nearest-rank)."""
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, math.ceil(p / 100.0 * len(s)) - 1))
    return s[k]


def pairs(samples: Iterable[Sample], fx: Callable[[Sample], float | None],
          fy: Callable[[Sample], float | None]) -> tuple[list[float], list[float]]:
    xs, ys = [], []
    for s in samples:
        x, y = fx(s), fy(s)
        if x is None or y is None:
            continue
        xs.append(float(x))
        ys.append(float(y))
    return xs, ys


def byte_at(i: int) -> Callable[[Sample], int | None]:
    return lambda s: s.payload[i] if len(s.payload) > i else None


def rpm_word(s: Sample) -> float | None:
    if len(s.payload) < 8:
        return None
    return ((s.payload[6] << 8) | s.payload[7]) / 8.0


def obd(name: str) -> Callable[[Sample], float | None]:
    return lambda s: s.obd.get(name)


def by_source(samples: Iterable[Sample]) -> dict[str, list[Sample]]:
    out: dict[str, list[Sample]] = {}
    for s in samples:
        out.setdefault(s.source, []).append(s)
    return out


def correlated_with_obd(samples: Iterable[Sample]) -> dict[str, list[Sample]]:
    groups = by_source(s for s in samples if s.kind == "correlated")
    return {k: v for k, v in groups.items()
            if any(x is not None for s in v for x in s.obd.values())}


def fmt(v: Any, nd: int = 3) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


# ------------------------------------------------------- seleção de arquivos
def select_files(logs_dir: Path, desde: str | None = None
                 ) -> tuple[list[Path], list[tuple[str, str]]]:
    """Arquivos com timestamp no nome >= desde. Devolve (selecionados, pulados)."""
    selected: list[Path] = []
    skipped: list[tuple[str, str]] = []
    for p in sorted(logs_dir.iterdir()):
        if not p.is_file():
            continue
        ts = file_timestamp(p.name)
        if desde is not None:
            if ts is None:
                skipped.append((p.name, "sem timestamp no nome (filtro --desde)"))
                continue
            if ts < desde:
                continue          # fora do período: não entra nem como pulado
        selected.append(p)
    return selected, skipped


def classify(name: str) -> str | None:
    n = name.lower()
    if n.startswith("analise_"):
        return "report"
    if n.endswith(".csv"):
        return "csv"
    if n.startswith("roteiro_") and n.endswith(".txt"):
        return "roteiro"
    if not n.endswith(".json"):
        return "text"
    if n.startswith("correlated_"):
        return "correlated"
    if n.startswith("reverse_state_"):
        return "reverse"
    if n.startswith("tcm_snapshot_") or n.startswith("snapshot_tcm"):
        return "snapshot"
    if n.startswith("field_test") or "seletor" in n:
        return "field_test"
    return None


SKIP_REASONS = {
    "report": "relatório de análise anterior",
    "csv": "CSV não lido (o JSON correspondente tem o hex cru)",
    "roteiro": "registro do roteiro (sem payload; só referência)",
    "text": "texto/outro formato não analisado",
    None: "JSON sem LID 0x01 do TCM reconhecível (formato não suportado)",
}


def _hex_to_bytes(h: Any) -> bytes | None:
    if not isinstance(h, str):
        return None
    try:
        return bytes.fromhex(h.replace(" ", ""))
    except ValueError:
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _walk_payloads(obj: Any, ctx: str | None = None):
    """Gera (label, hex) para chaves de hex em JSON aninhado (field tests)."""
    if isinstance(obj, dict):
        lbl = obj.get("label") or obj.get("scenario") or ctx
        for k, v in obj.items():
            if k in HEX_KEYS and isinstance(v, str):
                yield (lbl or "?"), v
            elif isinstance(v, (dict, list)):
                yield from _walk_payloads(v, lbl if lbl else k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_payloads(v, ctx)


def parse_log(name: str, data: Any, kind: str) -> FileResult:
    """Extrai as amostras de um JSON já carregado."""
    samples: list[Sample] = []
    if kind == "correlated":
        recs = data.get("records", []) if isinstance(data, dict) else []
        label = (data.get("label") if isinstance(data, dict) else None) or name
        for i, r in enumerate(recs):
            p = _hex_to_bytes(r.get("lid01_hex"))
            if not p:
                continue
            samples.append(Sample(
                source=name, kind=kind, label=str(label), payload=p,
                index=r.get("i", i), t=_num(r.get("t")),
                obd={k: _num(r.get(f"obd_{k}")) for k in OBD_SIGNALS},
                times={"tcm": _num(r.get("t_tcm")),
                       **{k: _num(r.get(f"t_{k}")) for k in OBD_SIGNALS}},
            ))
        note = "com started_at" if isinstance(data, dict) and "started_at" in data else ""
        return FileResult(name, kind, samples, records=len(recs), note=note)
    if kind == "reverse":
        recs = data.get("registros", []) if isinstance(data, dict) else []
        for i, r in enumerate(recs):
            p = _hex_to_bytes(r.get("raw_hex"))
            if p:
                samples.append(Sample(name, kind, "reverse_state_R", p,
                                      index=r.get("i", i), t=_num(r.get("t"))))
        return FileResult(name, kind, samples, records=len(recs))
    if kind == "snapshot":
        if not isinstance(data, dict):
            return FileResult(name, kind, [])
        module = data.get("module")
        if module not in (None, "tcm_cvt"):
            return FileResult(name, kind, [], note=f"módulo {module}")
        lids = data.get("lids") or {}
        for k, v in lids.items():
            try:
                lid = int(str(k), 16)
            except ValueError:
                continue
            p = _hex_to_bytes(v)
            if lid == 0x01 and p:
                samples.append(Sample(name, kind, str(data.get("label") or name), p))
        return FileResult(name, kind, samples, records=1)
    if kind == "field_test":
        n = 0
        for i, (lbl, h) in enumerate(_walk_payloads(data)):
            n += 1
            p = _hex_to_bytes(h)
            if p:
                samples.append(Sample(name, kind, str(lbl), p, index=i))
        nulls = sum(1 for v in data.values() if v is None) if isinstance(data, dict) else 0
        note = f"{nulls} cenário(s) sem captura (null)" if nulls else ""
        return FileResult(name, kind, samples, records=n, note=note)
    return FileResult(name, kind, [])


def load_logs(paths: list[Path]) -> tuple[list[FileResult], list[tuple[str, str]]]:
    files: list[FileResult] = []
    skipped: list[tuple[str, str]] = []
    for p in paths:
        kind = classify(p.name)
        if kind == "csv" and not p.with_suffix(".json").exists():
            skipped.append((p.name, "CSV sem JSON correspondente (não lido; sem hex cru garantido)"))
            continue
        if kind not in ("correlated", "reverse", "snapshot", "field_test"):
            skipped.append((p.name, SKIP_REASONS[kind]))
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            skipped.append((p.name, f"JSON ilegível: {e}"))
            continue
        fr = parse_log(p.name, data, kind)
        if not fr.samples:
            why = "nenhum payload do LID 0x01"
            skipped.append((p.name, f"{why}{' — ' + fr.note if fr.note else ''}"))
            continue
        files.append(fr)
    return files, skipped


# ------------------------------------------------------------------ análises
def analyze_inventory(files: list[FileResult], skipped: list[tuple[str, str]]) -> dict:
    by_kind: dict[str, int] = {}
    for f in files:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + len(f.samples)
    return {
        "files": [{"name": f.name, "kind": f.kind, "records": f.records,
                   "payloads": len(f.samples), "note": f.note} for f in files],
        "skipped": list(skipped),
        "total_payloads": sum(len(f.samples) for f in files),
        "by_kind": by_kind,
    }


def analyze_integrity(samples: list[Sample]) -> dict:
    checks = ["len69", "b0_lid", "b68_end"] + [f"b{i}_zero" for i in STATIC_ZERO_BYTES] \
        + ["b30_inv_b9"]
    ok = {c: 0 for c in checks}
    tested = {c: 0 for c in checks}
    exceptions: list[dict] = []

    def check(c: str, cond: bool, s: Sample, detail: str) -> None:
        tested[c] += 1
        if cond:
            ok[c] += 1
        else:
            exceptions.append({"source": s.source, "index": s.index, "label": s.label,
                               "check": c, "detail": detail})

    for s in samples:
        p = s.payload
        check("len69", len(p) == LID01_LEN, s, f"len={len(p)}")
        if len(p) >= 1:
            check("b0_lid", p[0] == 0x01, s, f"[0]=0x{p[0]:02X}")
        if len(p) >= LID01_LEN:
            check("b68_end", p[68] == END_MARKER, s, f"[68]=0x{p[68]:02X}")
            for i in STATIC_ZERO_BYTES:
                check(f"b{i}_zero", p[i] == 0, s, f"[{i}]=0x{p[i]:02X}")
            check("b30_inv_b9", abs(p[30] - (255 - p[9])) <= 1, s,
                  f"[9]={p[9]} [30]={p[30]} (255-[9]={255 - p[9]})")
    return {"n": len(samples), "checks": checks, "ok": ok, "tested": tested,
            "exceptions": exceptions}


def obd_at_tcm_time(ss: list[Sample], fx: Callable[[Sample], float | None],
                    sig: str) -> tuple[list[float], list[float]]:
    """Pares (valor do TCM, valor do OBD interpolado no instante da leitura do TCM).

    As leituras são em sequência (o OBD vem ~0,4 s depois do TCM); em transiente
    isso derruba o r sem que o decoder esteja errado. Só usa amostras com os dois
    carimbos de tempo; interpola linearmente entre as duas leituras OBD que cercam
    o instante do TCM.
    """
    pts = sorted((s.times[sig], s.obd[sig]) for s in ss
                 if s.times.get(sig) is not None and s.obd.get(sig) is not None)
    xs: list[float] = []
    ys: list[float] = []
    for s in ss:
        t = s.times.get("tcm")
        x = fx(s)
        if t is None or x is None:
            continue
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t1 > t0 and t0 <= t <= t1:
                xs.append(float(x))
                ys.append(v0 + (v1 - v0) * (t - t0) / (t1 - t0))
                break
    return xs, ys


def analyze_confirmed(samples: list[Sample]) -> dict:
    """[6,7]/8 vs RPM e [3],[4] vs VSP por captura correlacionada com OBD.

    `r` é o bruto. `r_comp` é o r com o OBD interpolado no instante do TCM (só com
    carimbos de tempo). `regression` usa `r_comp` quando existe. `indeterminate`
    vale quando não há variação para correlacionar (ex.: carro parado): isso não é
    regressão.
    """
    fields = (("[6,7]/8", rpm_word, "RPM"), ("[3]", byte_at(3), "VSP"),
              ("[4]", byte_at(4), "VSP"))
    out = []
    for src, ss in sorted(correlated_with_obd(samples).items()):
        for name, fx, sig in fields:
            xs, ys = pairs(ss, fx, obd(sig))
            r = pearson(xs, ys)
            cx, cy = obd_at_tcm_time(ss, fx, sig)
            r_comp = pearson(cx, cy) if len(cx) >= 3 else None
            r_eff = r_comp if r_comp is not None else r
            md = statistics.fmean([x - y for x, y in zip(xs, ys)]) if xs else None
            out.append({"source": src, "field": name, "signal": sig, "n": len(xs), "r": r,
                        "r_comp": r_comp, "indeterminate": r_eff is None,
                        "mean_diff": md,
                        "range": (min(ys), max(ys)) if ys else None,
                        "regression": r_eff is not None and r_eff < R_REGRESSION_LIMIT})
    all_corr = {s.source for s in samples if s.kind == "correlated"}
    no_obd = sorted(all_corr - set(correlated_with_obd(samples)))
    return {"rows": out, "limit": R_REGRESSION_LIMIT, "no_obd": no_obd}


def analyze_timing(samples: list[Sample]) -> dict:
    out = []
    for src, ss in sorted(by_source(s for s in samples if s.kind == "correlated").items()):
        has = any(s.times.get("tcm") is not None for s in ss)
        row: dict[str, Any] = {"source": src, "available": has}
        if has:
            for sig in ("VSP", "RPM"):
                d = [s.times[sig] - s.times["tcm"] for s in ss
                     if s.times.get(sig) is not None and s.times.get("tcm") is not None]
                row[sig] = {"n": len(d), "p50": percentile(d, 50), "p95": percentile(d, 95),
                            "max": max(d) if d else None}
        out.append(row)
    return {"rows": out}


def _downsample(ss: list[Sample], k: int = 12) -> list[Sample]:
    if len(ss) <= k:
        return list(ss)
    step = (len(ss) - 1) / (k - 1)
    return [ss[round(i * step)] for i in range(k)]


def analyze_cold_start(samples: list[Sample]) -> dict:
    out = []
    for src, ss in sorted(correlated_with_obd(samples).items()):
        ss = [s for s in ss if len(s.payload) >= LID01_LEN]
        row: dict[str, Any] = {"source": src, "n": len(ss), "bytes": {}}
        ect = [s.obd.get("ECT") for s in ss if s.obd.get("ECT") is not None]
        row["ect_first"] = ect[0] if ect else None
        row["ect_last"] = ect[-1] if ect else None
        for b in (9, 30, 10):
            xs, ys = pairs(ss, byte_at(b), obd("ECT"))
            xt, yt = pairs(ss, byte_at(b), lambda s: s.t)
            row["bytes"][b] = {"first": ss[0].payload[b] if ss else None,
                               "last": ss[-1].payload[b] if ss else None,
                               "r_ect": pearson(xs, ys), "n_ect": len(xs),
                               "r_t": pearson(xt, yt)}
        row["series"] = [(s.t, s.obd.get("ECT"), s.payload[9], s.payload[30], s.payload[10])
                         for s in _downsample(ss)]
        out.append(row)
    return {"rows": out}


_SEL_RE = re.compile(r"(?:^|_)([PNDR])(?=_|\d|$)")


def selector_from_label(label: str, kind: str = "") -> str | None:
    """Posição do seletor declarada no rótulo (ou R para reverse_state)."""
    if kind == "reverse":
        return "R"
    m = _SEL_RE.search(label or "")
    return m.group(1) if m else None


def analyze_selector(samples: list[Sample]) -> dict:
    groups: dict[tuple[str, str], list[Sample]] = {}
    for s in samples:
        if len(s.payload) < LID01_LEN:
            continue
        sel = selector_from_label(s.label, s.kind)
        if sel is None:
            continue
        groups.setdefault((s.source, s.label), []).append(s)
    rows = []
    tot_match = tot = 0
    for (src, lbl), ss in sorted(groups.items()):
        sel = selector_from_label(lbl, ss[0].kind)
        exp = SELECTOR_NIBBLE[sel]
        nib: dict[int, int] = {}
        b54: dict[int, int] = {}
        rng: dict[tuple[int, int, int], int] = {}
        for s in ss:
            nib[s.payload[54] >> 4] = nib.get(s.payload[54] >> 4, 0) + 1
            b54[s.payload[54]] = b54.get(s.payload[54], 0) + 1
            key = tuple(s.payload[23:26])
            rng[key] = rng.get(key, 0) + 1
        match = nib.get(exp, 0)
        tot_match += match
        tot += len(ss)
        rows.append({"source": src, "label": lbl, "selector": sel, "expected": exp,
                     "n": len(ss), "match": match, "nibbles": nib, "b54": b54,
                     "range": rng})
    return {"rows": rows, "match": tot_match, "n": tot}


def _band(v: float) -> str:
    for lo, hi, name in SPEED_BANDS:
        if lo <= round(v) <= hi:
            return name
    return "?"


def analyze_lockup_throttle(samples: list[Sample]) -> dict:
    corr = correlated_with_obd(samples)
    bands: dict[str, dict[int, int]] = {}
    for ss in corr.values():
        for s in ss:
            v = s.obd.get("VSP")
            if v is None or len(s.payload) < LID01_LEN:
                continue
            d = bands.setdefault(_band(v), {})
            d[s.payload[38]] = d.get(s.payload[38], 0) + 1
    rows = []
    for src, ss in sorted(corr.items()):
        row = {"source": src}
        for key, fx, fy in (("b19_tps", byte_at(19), obd("TPS")),
                            ("b19_rpm", byte_at(19), obd("RPM")),
                            ("tps_rpm", obd("TPS"), obd("RPM"))):
            xs, ys = pairs(ss, fx, fy)
            row[key] = pearson(xs, ys)
            row[key + "_n"] = len(xs)
        rows.append(row)
    order = [b[2] for b in SPEED_BANDS]
    return {"bands": {k: bands[k] for k in order if k in bands}, "rows": rows}


KNOWN_BYTES = {3: "VSP ✅", 4: "VSP ✅", 6: "RPM ✅ (byte alto)", 7: "RPM ✅ (byte baixo)",
               11: "espelho VSP 🟡", 12: "espelho VSP 🟡", 15: "espelha [6]"}


def analyze_byte_scan(samples: list[Sample], limit: float = SCAN_R_LIMIT,
                      min_n: int = SCAN_MIN_N) -> dict:
    """r de cada byte 1..67 com cada sinal OBD, por captura correlacionada."""
    hits = []
    tail: dict[int, dict] = {}
    for src, ss in sorted(correlated_with_obd(samples).items()):
        ss = [s for s in ss if len(s.payload) >= LID01_LEN]
        for b in range(1, 68):
            for sig in OBD_SIGNALS:
                xs, ys = pairs(ss, byte_at(b), obd(sig))
                if len(xs) < min_n:
                    continue
                r = pearson(xs, ys)
                if r is None:
                    continue
                if abs(r) >= limit:
                    hits.append({"source": src, "byte": b, "signal": sig, "r": r,
                                 "n": len(xs), "known": KNOWN_BYTES.get(b, "")})
                if 48 <= b <= 67:
                    cur = tail.get(b)
                    if cur is None or abs(r) > abs(cur["r"]):
                        tail[b] = {"r": r, "signal": sig, "source": src}
    distinct = {b: len({s.payload[b] for s in samples if len(s.payload) >= LID01_LEN})
                for b in range(48, 68)}
    hits.sort(key=lambda h: -abs(h["r"]))
    return {"hits": hits, "tail": tail, "distinct": distinct, "limit": limit,
            "min_n": min_n}


def run_all(files: list[FileResult], skipped: list[tuple[str, str]]) -> dict:
    samples = [s for f in files for s in f.samples]
    return {
        "inventory": analyze_inventory(files, skipped),
        "integrity": analyze_integrity(samples),
        "confirmed": analyze_confirmed(samples),
        "timing": analyze_timing(samples),
        "cold": analyze_cold_start(samples),
        "selector": analyze_selector(samples),
        "lockup": analyze_lockup_throttle(samples),
        "scan": analyze_byte_scan(samples),
    }


# --------------------------------------------------------------- relatório
def _counts(d: dict, hexfmt: bool = True) -> str:
    items = sorted(d.items(), key=lambda kv: -kv[1])
    return ", ".join((f"0x{k:02X}" if hexfmt and isinstance(k, int) else str(k)) + f": {v}"
                     for k, v in items)


def render_report(res: dict, meta: dict) -> str:
    L: list[str] = []
    a = L.append
    a("# Análise dos logs do LID 0x01 (TCM CVT)")
    a("")
    a(f"- Gerado: {meta.get('generated', '')}")
    a(f"- Pasta: `{meta.get('logs', '')}`; filtro --desde: {meta.get('desde') or 'nenhum'}")
    a("- Veículo de teste: Nissan Sentra B16 2010, CVT JF011E, TCM 0x7E1/0x7E9, GODIAG "
      "GD101. Não generalizar para outros veículos.")
    a("- ✅ = achado confirmado anteriormente (aqui só reconferido). Todo o resto é "
      "**hipótese não verificada**. O hex cru fica nos arquivos de origem.")
    a("")

    inv = res["inventory"]
    a("## 1. Inventário")
    a("")
    a(f"{inv['total_payloads']} payloads em {len(inv['files'])} arquivo(s). Por tipo: "
      + (", ".join(f"{k}={v}" for k, v in sorted(inv["by_kind"].items())) or "—"))
    a("")
    if inv["files"]:
        a("| Arquivo | Tipo | Registros | Payloads | Nota |")
        a("|---|---|---|---|---|")
        for f in inv["files"]:
            a(f"| `{f['name']}` | {f['kind']} | {f['records']} | {f['payloads']} | {f['note']} |")
        a("")
    a(f"Pulados: {len(inv['skipped'])}")
    a("")
    if inv["skipped"]:
        a("| Arquivo | Motivo |")
        a("|---|---|")
        for n, why in inv["skipped"]:
            a(f"| `{n}` | {why} |")
        a("")

    ig = res["integrity"]
    a("## 2. Integridade")
    a("")
    names = {"len69": "comprimento 69", "b0_lid": "[0] = 0x01", "b68_end": "[68] = 0x5F",
             "b30_inv_b9": "[30] = 255−[9] (±1) — relação observada, significado não verificado"}
    a("| Verificação | OK / testados |")
    a("|---|---|")
    for c in ig["checks"]:
        label = names.get(c) or f"[{c[1:].split('_')[0]}] = 0x00"
        a(f"| {label} | {ig['ok'][c]}/{ig['tested'][c]} |")
    a("")
    if ig["exceptions"]:
        a(f"Exceções ({len(ig['exceptions'])}, até 30):")
        a("")
        for e in ig["exceptions"][:30]:
            a(f"- `{e['source']}` #{e['index']} ({e['label']}): {e['check']} — {e['detail']}")
    else:
        a("Nenhuma exceção.")
    a("")

    cf = res["confirmed"]
    a("## 3. Campos confirmados — reconferência com OBD")
    a("")
    if not cf["rows"]:
        a("Não disponível: nenhuma captura correlacionada com valores OBD.")
    else:
        a(f"Alerta se r < {cf['limit']} (regressão de um achado ✅). Diferença média = "
          "TCM − OBD.")
        a("")
        a("r comp. = r com o OBD interpolado no instante da leitura do TCM (descontando a "
          "defasagem entre as leituras); \"—\" quando a captura não tem carimbos de tempo.")
        a("")
        a("| Captura | Campo | PID | n | r | r comp. | Dif. média | Faixa OBD | Status |")
        a("|---|---|---|---|---|---|---|---|---|")
        for r in cf["rows"]:
            rg = f"{r['range'][0]:g}–{r['range'][1]:g}" if r["range"] else "—"
            if r["indeterminate"]:
                st = "➖ indeterminado (sem variação para correlacionar)"
            elif r["regression"]:
                st = "⚠️ REGRESSÃO"
            else:
                st = "✅ ok"
            a(f"| `{r['source']}` | {r['field']} | {r['signal']} | {r['n']} | {fmt(r['r'])} "
              f"| {fmt(r['r_comp'])} | {fmt(r['mean_diff'], 2)} | {rg} | {st} |")
    if cf["no_obd"]:
        a("")
        a("Capturas correlacionadas sem nenhum valor OBD (fora das seções 3, 5, 7 e 8): "
          + ", ".join(f"`{n}`" for n in cf["no_obd"]))
    a("")

    tm = res["timing"]
    a("## 4. Defasagem de tempo TCM × OBD")
    a("")
    if not tm["rows"]:
        a("Não disponível: nenhuma captura correlacionada.")
    for r in tm["rows"]:
        if not r["available"]:
            a(f"- `{r['source']}`: não disponível (captura antiga, sem t_tcm).")
            continue
        parts = []
        for sig in ("VSP", "RPM"):
            d = r[sig]
            parts.append(f"t_{sig}−t_tcm n={d['n']} p50={fmt(d['p50'])} s "
                         f"p95={fmt(d['p95'])} s máx={fmt(d['max'])} s")
        a(f"- `{r['source']}`: " + "; ".join(parts))
    a("")

    cs = res["cold"]
    a("## 5. Partida a frio — [9], [30], [10] × ECT (hipótese não verificada)")
    a("")
    if not cs["rows"]:
        a("Não disponível: nenhuma captura correlacionada com OBD.")
    for r in cs["rows"]:
        a(f"### `{r['source']}` (n={r['n']}; ECT {fmt(r['ect_first'], 1)} → "
          f"{fmt(r['ect_last'], 1)} °C)")
        a("")
        a("| Byte | Primeiro | Último | r vs ECT (n) | r vs tempo |")
        a("|---|---|---|---|---|")
        for b, d in r["bytes"].items():
            a(f"| [{b}] | {d['first']} | {d['last']} | {fmt(d['r_ect'])} ({d['n_ect']}) "
              f"| {fmt(d['r_t'])} |")
        a("")
        a("| t (s) | ECT | [9] | [30] | [10] |")
        a("|---|---|---|---|---|")
        for t, e, b9, b30, b10 in r["series"]:
            a(f"| {fmt(t, 1)} | {fmt(e, 1)} | {b9} | {b30} | {b10} |")
        a("")

    sl = res["selector"]
    a("## 6. Seletor — nibble alto de [54] (P=1, N=4, D=8, R=2) — hipótese não verificada")
    a("")
    if not sl["rows"]:
        a("Não disponível: nenhuma captura com seletor no rótulo.")
    else:
        a(f"Batem: {sl['match']}/{sl['n']} payloads. O seletor vem só do rótulo da captura "
          "(não foi medido).")
        a("")
        a("| Captura | Rótulo | Sel. | n | Batem | [54] | [23-25] |")
        a("|---|---|---|---|---|---|---|")
        for r in sl["rows"]:
            rng = ", ".join(f"{k}: {v}" for k, v in sorted(r["range"].items(), key=lambda kv: -kv[1]))
            flag = "" if r["match"] == r["n"] else " ❌"
            a(f"| `{r['source']}` | {r['label']} | {r['selector']} | {r['n']} | "
              f"{r['match']}{flag} | {_counts(r['b54'])} | {rng} |")
    a("")

    lk = res["lockup"]
    a("## 7. Lock-up [38] e borboleta [19-22] — hipóteses não verificadas")
    a("")
    if not lk["bands"]:
        a("[38] por faixa: não disponível (sem VSP OBD).")
    else:
        a("| Faixa VSP OBD (km/h) | Valores de [38] |")
        a("|---|---|")
        for band, d in lk["bands"].items():
            a(f"| {band} | {_counts(d)} |")
    a("")
    for r in lk["rows"]:
        a(f"- `{r['source']}`: r([19], TPS)={fmt(r['b19_tps'])} (n={r['b19_tps_n']}); "
          f"r([19], RPM)={fmt(r['b19_rpm'])} (n={r['b19_rpm_n']}); "
          f"r(TPS, RPM)={fmt(r['tps_rpm'])}")
    if lk["rows"]:
        a("")
        a("Nota: TPS e RPM andam juntos nestas capturas; r alto de [19] com os dois não "
          "separa borboleta de rotação. Precisa de captura com acelerador variando em RPM fixo.")
    a("")

    sc = res["scan"]
    a(f"## 8. Varredura de bytes 1..67 × OBD (|r| ≥ {sc['limit']}, n ≥ {sc['min_n']}) — "
      "candidatos, não verificados")
    a("")
    if not sc["hits"]:
        a("Nenhum byte acima do limite (ou sem captura correlacionada com OBD).")
    else:
        a("| Captura | Byte | PID | r | n | Já conhecido |")
        a("|---|---|---|---|---|---|")
        for h in sc["hits"][:40]:
            a(f"| `{h['source']}` | [{h['byte']}] | {h['signal']} | {fmt(h['r'])} | {h['n']} "
              f"| {h['known']} |")
        if len(sc["hits"]) > 40:
            a(f"\n… mais {len(sc['hits']) - 40} acima do limite.")
    a("")
    a("### Bytes [48-67]")
    a("")
    a("| Byte | Valores distintos | Maior abs(r) | PID | Captura |")
    a("|---|---|---|---|---|")
    for b in range(48, 68):
        t = sc["tail"].get(b)
        if t:
            a(f"| [{b}] | {sc['distinct'][b]} | {fmt(t['r'])} | {t['signal']} | `{t['source']}` |")
        else:
            a(f"| [{b}] | {sc['distinct'][b]} | — | — | — |")
    a("")
    return "\n".join(L)


# ----------------------------------------------------------------------- I/O
def choose_output(out: str | None, logs_dir: Path, now: dt.datetime) -> Path:
    """Caminho do relatório; nunca um arquivo existente."""
    if out:
        p = Path(out)
        if p.exists():
            raise FileExistsError(f"{p} já existe; não sobrescrevo")
        return p
    base = logs_dir / f"analise_{now.strftime('%Y%m%d_%H%M%S')}.md"
    p, n = base, 1
    while p.exists():
        p = base.with_name(f"{base.stem}_{n}.md")
        n += 1
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Análise pós-teste dos logs do LID 0x01 do TCM.")
    ap.add_argument("--desde", help="só arquivos com timestamp no nome >= YYYYMMDD_HHMMSS")
    ap.add_argument("--logs", default=str(Path(__file__).resolve().parent / "logs"),
                    help="pasta dos logs (default: logs/)")
    ap.add_argument("--out", help="arquivo .md de saída (default: logs/analise_<ts>.md)")
    args = ap.parse_args(argv)

    if args.desde and not DESDE_RE.match(args.desde):
        print(f"--desde inválido: {args.desde!r} (use YYYYMMDD_HHMMSS)", file=sys.stderr)
        return 2
    logs_dir = Path(args.logs)
    if not logs_dir.is_dir():
        print(f"Pasta não encontrada: {logs_dir}", file=sys.stderr)
        return 2
    now = dt.datetime.now()
    try:
        out = choose_output(args.out, logs_dir, now)
    except FileExistsError as e:
        print(str(e), file=sys.stderr)
        return 2

    paths, skipped = select_files(logs_dir, args.desde)
    files, skipped2 = load_logs(paths)
    res = run_all(files, skipped + skipped2)
    text = render_report(res, {"generated": now.isoformat(timespec="seconds"),
                               "logs": str(logs_dir), "desde": args.desde})
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as f:     # "x": falha se já existir
        f.write(text)
    print(f"{res['inventory']['total_payloads']} payloads; relatório: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
