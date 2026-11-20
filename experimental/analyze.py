"""
Analisa o CSV gerado por capture.py, cruzando os MARKERs (eventos que
você anotou enquanto navegava no Consult-III) com os IDs CAN que
mudaram de valor perto de cada marcação.

Isso reduz "todos os IDs no barramento" pra "candidatos prováveis" de
corresponderem ao dado que você estava olhando naquele momento.

Suporta dois formatos de linha de dado (gerados por capture.py):
  - CAN_FRAME: já vem com can_id em hex e data em hex (modo socketcan)
  - CAN_RAW:   texto crú vindo do adaptador em modo ELM/ATMA — o formato
    exato varia por adaptador/firmware, então o parser aqui é tolerante
    e best-effort. Linhas que não conseguir entender são contadas e
    reportadas, não descartadas silenciosamente.
"""
from __future__ import annotations

import csv
import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import click

# Formato real confirmado via driver can327 do kernel Linux
# (docs.kernel.org/.../can327.rst) pra modo monitor (ATMA) de ELM327/STN:
#   ID(hex) ESPAÇO [DLC(decimal) ESPAÇO] DADOS(hex contínuo, sem espaço)
# Ex. com DLC (ATD1 ligado):
#   "7E8 8 0310410C1A000000"
# Ex. sem DLC (firmware não suporta ATD1, ou ATD1 falhou e seguimos sem
# ele — ver capture.py):
#   "7E8 0310410C1A000000"
# Também tolera o formato espaçado entre bytes (caso algum firmware/clone
# se comporte diferente do driver de referência):
#   "7E8 03 10 41 0C 1A 00 00 00"
_RAW_LINE_RE = re.compile(
    r"^\s*([0-9A-Fa-f]{3,8})\s+(?:(\d{1,2})\s+)?((?:[0-9A-Fa-f]{2}\s*)+)$"
)

# Linhas de controle/ruído do próprio adaptador que não são frames CAN —
# ignoradas silenciosamente (não contam como "não reconhecida", porque
# não é um erro de parsing, é esperado aparecerem de vez em quando).
_NOISE_LINES = {
    "atma", "ok", ">", "searching...", "searching", "buffer full",
    "stopped", "no data", "can error",
}


@dataclass
class Frame:
    timestamp: dt.datetime
    can_id: str  # hex normalizado, ex "7E8"
    data: str  # hex bytes, ex "4100BE"
    dlc: int | None = None  # tamanho declarado pelo adaptador (ATD1), se presente


@dataclass
class Marker:
    timestamp: dt.datetime
    label: str


def _parse_timestamp(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def load_log(path: Path) -> tuple[list[Frame], list[Marker], int]:
    frames: list[Frame] = []
    markers: list[Marker] = []
    unparsed = 0

    with path.open(newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if len(row) < 4:
                continue
            ts_str, kind, id_or_seq, data_or_label = row[0], row[1], row[2], row[3]
            ts = _parse_timestamp(ts_str)

            if kind == "MARKER":
                markers.append(Marker(ts, data_or_label))
            elif kind == "CAN_FRAME":
                frames.append(Frame(ts, id_or_seq.lower().replace("0x", ""), data_or_label.lower()))
            elif kind == "CAN_RAW":
                raw = data_or_label.strip()
                if raw.lower() in _NOISE_LINES:
                    continue
                m = _RAW_LINE_RE.match(raw)
                if m:
                    can_id = m.group(1).lower()
                    dlc = int(m.group(2)) if m.group(2) is not None else None
                    data = m.group(3).replace(" ", "").lower()
                    frames.append(Frame(ts, can_id, data, dlc))
                else:
                    unparsed += 1

    return frames, markers, unparsed


def analyze(path: Path, window_seconds: float = 2.0) -> None:
    frames, markers, unparsed = load_log(path)

    click.echo(f"Frames entendidos: {len(frames)} | Marcadores: {len(markers)} | "
               f"Linhas não reconhecidas: {unparsed}")
    if unparsed:
        click.echo(
            "  (linhas não reconhecidas podem indicar que o formato de saída do "
            "seu adaptador é diferente do esperado — ajuste _RAW_LINE_RE em "
            "analyze.py depois de ver um exemplo real)"
        )

    if not markers:
        click.echo("Nenhum marcador encontrado — nada pra correlacionar.")
        return

    by_id: dict[str, list[Frame]] = defaultdict(list)
    for fr in frames:
        by_id[fr.can_id].append(fr)
    for lst in by_id.values():
        lst.sort(key=lambda f: f.timestamp)

    window = dt.timedelta(seconds=window_seconds)

    for marker in markers:
        click.echo(f"\n=== Marcador: '{marker.label}' @ {marker.timestamp.isoformat()} ===")
        before_start = marker.timestamp - window
        after_end = marker.timestamp + window

        candidates: list[tuple[str, str, str]] = []  # (can_id, valor_antes, valor_depois)
        for can_id, lst in by_id.items():
            before_vals = {f.data for f in lst if before_start <= f.timestamp < marker.timestamp}
            after_vals = {f.data for f in lst if marker.timestamp <= f.timestamp <= after_end}
            if not before_vals or not after_vals:
                continue
            if before_vals != after_vals:
                candidates.append((can_id, next(iter(before_vals)), next(iter(after_vals))))

        if not candidates:
            click.echo("  Nenhum ID mudou de valor na janela — tente aumentar --window-seconds.")
            continue

        candidates.sort(key=lambda c: c[0])
        for can_id, before_val, after_val in candidates:
            click.echo(f"  ID {can_id}: {before_val} -> {after_val}")


@click.command()
@click.argument("log_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--window-seconds",
    default=2.0,
    show_default=True,
    help="Janela antes/depois de cada marcador pra comparar valores.",
)
def main(log_path: Path, window_seconds: float) -> None:
    """Correlaciona marcadores do capture.py com IDs CAN candidatos."""
    analyze(log_path, window_seconds)


if __name__ == "__main__":
    main()
