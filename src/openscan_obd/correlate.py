"""
Correlação de LIDs (Caminho B) — o motor de descoberta do CVT.

A ideia: os LIDs do TCM (serviço 0x21) devolvem bytes crus cujo significado
NÃO é público. Pra descobrir qual LID/byte é temperatura, RPM, pressão etc.,
tiramos "fotos" (snapshots) dos LIDs em ESTADOS diferentes do carro e
comparamos:
  - frio vs quente        -> o byte que subiu é temperatura
  - parado vs acelerando  -> o byte que mudou acompanha RPM/razão
  - P vs D                -> muda o indicador de marcha

Este módulo é a parte PURA (load/save/diff), testável sem carro. O snapshot
em si (ler do módulo) fica em scanner.py.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Snapshot:
    module: str
    label: str
    timestamp: str
    session: str          # subtipo de sessão usado (ex "0xC0") ou "nenhuma"
    lids: dict[str, str]  # {"0x80": "aabbcc", ...} — lid hex -> dados hex


def save_snapshot(snap: Snapshot, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(snap), indent=2), encoding="utf-8")


def load_snapshot(path: Path) -> Snapshot:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Snapshot(**d)


@dataclass
class LidDiff:
    lid: str
    before: str
    after: str
    changed_byte_positions: list[int]  # índices de byte que mudaram


def _changed_bytes(a_hex: str, b_hex: str) -> list[int]:
    """Índices (0-based) dos bytes que diferem entre dois hex de mesmo tamanho.
    Se tamanhos diferem, retorna [-1] (mudança estrutural)."""
    a = bytes.fromhex(a_hex) if a_hex else b""
    b = bytes.fromhex(b_hex) if b_hex else b""
    if len(a) != len(b):
        return [-1]
    return [i for i in range(len(a)) if a[i] != b[i]]


def diff_snapshots(before: Snapshot, after: Snapshot) -> list[LidDiff]:
    """Compara dois snapshots, retornando só os LIDs cujo valor MUDOU.

    Esses são os candidatos a corresponder ao que mudou fisicamente no
    carro entre as duas fotos. Ordenado por LID.
    """
    diffs: list[LidDiff] = []
    for lid, before_val in before.lids.items():
        after_val = after.lids.get(lid)
        if after_val is None:
            continue  # LID sumiu — ignora (provável leitura instável)
        if before_val != after_val:
            diffs.append(LidDiff(lid, before_val, after_val, _changed_bytes(before_val, after_val)))
    diffs.sort(key=lambda d: int(d.lid, 16))
    return diffs


def format_diff_report(before: Snapshot, after: Snapshot, diffs: list[LidDiff]) -> str:
    lines = [
        f"Comparação: '{before.label}' -> '{after.label}'",
        f"Módulo: {before.module} | sessão: {before.session}",
        f"LIDs que mudaram: {len(diffs)}",
        "",
    ]
    for d in diffs:
        pos = "estrutura/tamanho" if d.changed_byte_positions == [-1] else f"bytes {d.changed_byte_positions}"
        lines.append(f"  LID {d.lid}: {d.before} -> {d.after}   (mudou: {pos})")
    if not diffs:
        lines.append("  (nenhum LID mudou — tente estados mais contrastantes, ou faixa de LID maior)")
    return "\n".join(lines)
