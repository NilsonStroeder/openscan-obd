"""Resumo estrutural de capturas JSONL, sem interpretar bytes do veículo."""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openscan_obd.gateway.capture import CAPTURE_SCHEMA_VERSION


def _parse_timestamp(value: Any, line_number: int) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"linha {line_number}: captured_at ausente ou inválido")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"linha {line_number}: captured_at inválido: {value}") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"linha {line_number}: captured_at deve incluir fuso horário")
    return timestamp


def summarize_capture(path: Path) -> dict[str, Any]:
    records: list[tuple[int, dict[str, Any], datetime]] = []
    with path.open(encoding="utf-8") as capture_file:
        for line_number, line in enumerate(capture_file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"linha {line_number}: JSON inválido: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"linha {line_number}: cada registro deve ser um objeto JSON")
            captured_at = _parse_timestamp(record.get("captured_at"), line_number)
            event = record.get("event")
            if not isinstance(event, str) or event not in {
                "capture_started", "frame", "capture_stopped",
            }:
                raise ValueError(f"linha {line_number}: evento desconhecido: {event!r}")
            if event == "frame" and not isinstance(record.get("frame"), dict):
                raise ValueError(f"linha {line_number}: evento frame sem objeto frame")
            records.append((line_number, record, captured_at))

    if not records:
        raise ValueError("captura vazia: nenhum registro JSONL encontrado")
    if records[0][1].get("event") != "capture_started":
        raise ValueError("captura inválida: primeiro registro deve ser capture_started")
    schema_version = records[0][1].get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError(
            "captura inválida: capture_started.schema_version deve ser inteiro"
        )
    if schema_version != CAPTURE_SCHEMA_VERSION:
        raise ValueError(
            f"versão de schema não suportada: {schema_version} "
            f"(suportada: {CAPTURE_SCHEMA_VERSION})"
        )
    metadata = records[0][1].get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("captura inválida: metadata deve ser um objeto JSON")
    if any(record["event"] == "capture_started" for _, record, _ in records[1:]):
        raise ValueError("captura inválida: evento capture_started duplicado")
    stopped = records[-1][1].get("event") == "capture_stopped"
    if any(record["event"] == "capture_stopped" for _, record, _ in records[:-1]):
        raise ValueError("captura inválida: capture_stopped não é o último registro")

    start_time = records[0][2]
    end_time = records[-1][2]
    if any(
        current[2] < previous[2]
        for previous, current in zip(records, records[1:])
    ):
        raise ValueError("captura inválida: timestamps fora de ordem")

    frame_records = [
        (record["frame"].get("ts"), record["frame"])
        for _, record, _ in records
        if record["event"] == "frame"
    ]
    connected_frames = 0
    disconnected_frames = 0
    lid_available_frames = 0
    lid_missing_frames = 0
    connection_outages = 0
    recoveries = 0
    lid_missing_periods = 0
    payload_changes = 0
    payloads: set[str] = set()
    previous_connection: bool | None = None
    previous_lid_available = False
    previous_payload: str | None = None
    previous_frame_timestamp: float | None = None
    open_outage: datetime | None = None
    connection_outage_durations: list[float] = []
    connection_outages_detail: list[dict[str, Any]] = []

    frame_times: list[datetime] = []
    for frame_timestamp, frame in frame_records:
        connection = frame.get("conn")
        lid_available = frame.get("lid_available")
        raw_payload = frame.get("raw_lid01")
        if (
            isinstance(frame_timestamp, bool)
            or not isinstance(frame_timestamp, (int, float))
            or not math.isfinite(frame_timestamp)
        ):
            raise ValueError("frame inválido: ts deve ser timestamp Unix finito")
        if (
            previous_frame_timestamp is not None
            and frame_timestamp < previous_frame_timestamp
        ):
            raise ValueError("frame inválido: ts fora de ordem")
        previous_frame_timestamp = frame_timestamp
        try:
            captured_at = datetime.fromtimestamp(frame_timestamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("frame inválido: ts fora do intervalo suportado") from exc
        frame_times.append(captured_at)
        if not isinstance(connection, bool):
            raise ValueError("frame inválido: conn deve ser boolean")
        if not isinstance(lid_available, bool):
            raise ValueError("frame inválido: lid_available deve ser boolean")
        if raw_payload is not None and not isinstance(raw_payload, str):
            raise ValueError("frame inválido: raw_lid01 deve ser string ou null")
        for field in (
            "data_source", "profile", "error", "decode_error",
            "lid_response", "raw_lid_response", "lid_nrc",
        ):
            value = frame.get(field)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"frame inválido: {field} deve ser string ou null")
        verified = frame.get("verified")
        if verified is not None and not isinstance(verified, bool):
            raise ValueError("frame inválido: verified deve ser boolean ou null")

        if connection:
            connected_frames += 1
        else:
            disconnected_frames += 1
        if connection and lid_available:
            lid_available_frames += 1
        elif connection:
            lid_missing_frames += 1
        if not connection and (previous_connection is not False):
            connection_outages += 1
            open_outage = captured_at
        if connection and previous_connection is False:
            recoveries += 1
            if open_outage is not None:
                duration = (captured_at - open_outage).total_seconds()
                connection_outage_durations.append(duration)
                connection_outages_detail.append({
                    "started_at": open_outage.isoformat(),
                    "ended_at": captured_at.isoformat(),
                    "duration_s": round(duration, 3),
                    "ongoing": False,
                })
                open_outage = None

        missing_lid_now = connection and not lid_available
        missing_lid_before = (
            previous_connection is True and not previous_lid_available
        )
        if missing_lid_now and not missing_lid_before:
            lid_missing_periods += 1

        if raw_payload is not None:
            payloads.add(raw_payload)
            if previous_payload is not None and raw_payload != previous_payload:
                payload_changes += 1
            previous_payload = raw_payload
        previous_connection = connection
        previous_lid_available = lid_available

    if open_outage is not None:
        duration = max(0.0, (end_time - open_outage).total_seconds())
        connection_outage_durations.append(duration)
        connection_outages_detail.append({
            "started_at": open_outage.isoformat(),
            "ended_at": None,
            "duration_s": round(duration, 3),
            "ongoing": True,
        })

    frame_intervals = [
        (current - previous).total_seconds()
        for previous, current in zip(frame_times, frame_times[1:])
    ]

    def percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = max(0, math.ceil(fraction * len(values)) - 1)
        return round(sorted(values)[index], 3)

    max_frame_gap = max(frame_intervals, default=None)

    return {
        "file": str(path),
        "metadata": metadata,
        "started_at": start_time.isoformat(),
        "ended_at": end_time.isoformat(),
        "duration_s": round((end_time - start_time).total_seconds(), 3),
        "complete": stopped,
        "frame_count": len(frame_records),
        "connected_frames": connected_frames,
        "disconnected_frames": disconnected_frames,
        "connection_outages": connection_outages,
        "recoveries": recoveries,
        "connection_outage_durations_s": [
            round(duration, 3) for duration in connection_outage_durations
        ],
        "max_connection_outage_s": round(max(connection_outage_durations), 3)
        if connection_outage_durations else None,
        "connection_outages_detail": connection_outages_detail,
        "lid_available_frames": lid_available_frames,
        "lid_missing_frames": lid_missing_frames,
        "lid_missing_periods": lid_missing_periods,
        "unique_raw_lid01_payloads": len(payloads),
        "raw_lid01_payload_changes": payload_changes,
        "raw_lid01_payloads": sorted(payloads),
        "frame_interval_count": len(frame_intervals),
        "frame_timing_source": "frame.ts (Unix timestamp do poller)",
        "frame_interval_percentile_method": "nearest_rank",
        "frame_interval_min_s": round(min(frame_intervals), 3) if frame_intervals else None,
        "frame_interval_p50_s": percentile(frame_intervals, 0.50),
        "frame_interval_p95_s": percentile(frame_intervals, 0.95),
        "frame_interval_max_s": round(max(frame_intervals), 3) if frame_intervals else None,
        "max_frame_gap_s": round(max_frame_gap, 3) if max_frame_gap is not None else None,
    }


def format_capture_summary(summary: dict[str, Any]) -> str:
    complete_label = "completa" if summary["complete"] else "incompleta (sem capture_stopped)"
    payloads = ", ".join(summary["raw_lid01_payloads"]) or "nenhum"
    return "\n".join([
        f"Captura: {summary['file']}",
        f"Estado: {complete_label}",
        f"Início: {summary['started_at']}",
        f"Fim: {summary['ended_at']}",
        f"Duração: {summary['duration_s']:.3f} s",
        f"Frames: {summary['frame_count']}",
        (
            f"Conexão: {summary['connected_frames']} conectados, "
            f"{summary['disconnected_frames']} desconectados; "
            f"{summary['connection_outages']} falhas e {summary['recoveries']} recuperações; "
            f"maior interrupção {summary['max_connection_outage_s']} s"
        ),
        (
            f"Intervalo entre frames: p50 {summary['frame_interval_p50_s']} s, "
            f"p95 {summary['frame_interval_p95_s']} s, "
            f"máximo/lacuna {summary['max_frame_gap_s']} s"
        ),
        f"Base temporal: {summary['frame_timing_source']}; percentis nearest-rank.",
        (
            f"LID 0x01: {summary['lid_available_frames']} respostas, "
            f"{summary['lid_missing_frames']} ausências em "
            f"{summary['lid_missing_periods']} períodos"
        ),
        (
            f"Payloads crus: {summary['unique_raw_lid01_payloads']} distintos; "
            f"{summary['raw_lid01_payload_changes']} mudanças consecutivas"
        ),
        f"Payloads hex observados (sem decodificação): {payloads}",
    ])
