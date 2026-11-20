"""CSV e relatório HTML offline para séries temporais de capturas KWP."""
from __future__ import annotations

import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openscan_obd.gateway.capture_analysis import summarize_capture

SIGNALS: dict[str, tuple[str, str]] = {
    "rpm": ("RPM (hipótese)", "rpm"),
    "vsp": ("Velocidade (hipótese)", "km/h"),
    "tps": ("Acelerador (hipótese)", "%"),
    "ect": ("Temperatura do líquido (hipótese)", "°C"),
    "iat": ("Temperatura do ar (hipótese)", "°C"),
    "inj_pw": ("Pulso de injeção (hipótese)", "ms"),
    "ign_adv": ("Avanço de ignição (hipótese)", "°"),
    "o2s1": ("O2S1 — tensão hipotética, não AFR/lambda", "V"),
    "stft": ("STFT (hipótese)", "%"),
    "ltft": ("LTFT (hipótese)", "%"),
}

CSV_COLUMNS = (
    "timestamp_utc",
    "elapsed_s",
    "vehicle",
    "ecu",
    "adapter",
    "vehicle_profile",
    "data_source",
    "conn",
    "lid_available",
    "raw_lid01_hex",
    "profile",
    "verified",
    *SIGNALS,
    "error",
    "decode_error",
)

HTML_TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Relatório de captura NissanScan</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #17212b; background: #f2f5f8; }
    * { box-sizing: border-box; }
    body { max-width: 1200px; margin: 0 auto; padding: 24px; }
    h1, h2 { margin-bottom: .4em; }
    .notice, .meta, .chart { border: 1px solid #d2dbe5; background: white; border-radius: 8px; padding: 14px; }
    .notice { border-left: 4px solid #dc9c28; margin: 16px 0; }
    .meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 8px 18px; }
    .meta div { overflow-wrap: anywhere; }
    .muted { color: #566575; }
    fieldset { display: flex; flex-wrap: wrap; gap: 8px 16px; border: 1px solid #d2dbe5; border-radius: 8px; margin: 18px 0; }
    label { white-space: nowrap; }
    .chart { margin: 14px 0; overflow: hidden; }
    .chart h2 { font-size: 1.05rem; }
    svg { display: block; width: 100%; height: 260px; }
    .empty { color: #687789; padding: 36px 10px; text-align: center; }
    .axis { stroke: #6f7e8d; stroke-width: 1; }
    .gridline { stroke: #e1e7ed; stroke-width: 1; }
    .series { fill: none; stroke: #1479bd; stroke-width: 2; vector-effect: non-scaling-stroke; }
    .tick, .axis-label { fill: #465565; font-size: 12px; }
    .gap { color: #596979; font-size: .9rem; }
    table { width: 100%; border-collapse: collapse; }
    th, td { text-align: left; padding: 6px; border-bottom: 1px solid #e5eaf0; }
    code { overflow-wrap: anywhere; }
    @media (max-width: 650px) { body { padding: 12px; } svg { height: 220px; } }
  </style>
</head>
<body>
  <h1>Captura de dados — NissanScan</h1>
  <p class="muted">Relatório offline. Visualização somente leitura; payloads crus não são decodificados aqui.</p>
  <section id="metadata" class="meta" aria-label="Metadados da captura"></section>
  <div class="notice"><strong>Valores experimentais.</strong> Perfil: <code id="profile"></code>.
    Os parâmetros e escalas disponíveis no arquivo podem ser hipóteses e não foram necessariamente
    validados no veículo. O2S1 é exibido como tensão hipotética; não equivale a AFR ou lambda confirmada.
    Lacunas de conexão, LID ou amostragem são mostradas como interrupções, sem interpolação.</div>
  <section class="meta" aria-label="Resumo da captura">
    <div>Estado: <strong id="complete"></strong></div>
    <div>Duração: <strong id="duration"></strong></div>
    <div>Frames: <strong id="frames"></strong></div>
    <div>Falhas / recuperações: <strong id="outages"></strong></div>
    <div>Maior interrupção: <strong id="outage-duration"></strong></div>
    <div>Intervalo p50 / p95: <strong id="intervals"></strong></div>
    <div>Maior lacuna entre frames: <strong id="gap"></strong></div>
    <div>Perfil(s): <strong id="profiles"></strong></div>
    <div>verified: <strong id="verified"></strong></div>
  </section>
  <fieldset>
    <legend>Sinais disponíveis — escolha os gráficos</legend>
    <div id="signal-options"></div>
  </fieldset>
  <section id="charts" aria-live="polite"></section>
  <details><summary>Payloads crus LID 0x01 vistos (hex)</summary><ul id="raw-payloads"></ul></details>
  <script>
    const REPORT = __REPORT_DATA__;
    const SIGNALS = __SIGNALS__;
    const COLORS = ["#1479bd", "#d16b16", "#398557", "#8a58a8", "#c1445a", "#168e91"];
    const $ = (id) => document.getElementById(id);
    const text = (id, value) => { $(id).textContent = value; };
    const fmt = (value, suffix = "") => value == null ? "—" : `${value}${suffix}`;
    const meta = REPORT.metadata || {};
    const metadata = [
      ["Veículo", meta.vehicle],
      ["ECU", meta.ecu],
      ["Adaptador/driver", meta.adapter],
      ["Perfil", meta.vehicle_profile],
      ["Origem", meta.mode],
      ["Validação", meta.validation_status || "não informada"],
      ["Início UTC", REPORT.started_at],
    ];
    for (const [label, value] of metadata) {
      const item = document.createElement("div");
      const strong = document.createElement("strong");
      strong.textContent = value || "não registrado";
      item.append(`${label}: `, strong);
      $("metadata").append(item);
    }
    text("profile", REPORT.profiles.join(", ") || "não informado");
    text("complete", REPORT.complete ? "completa" : "incompleta");
    text("duration", fmt(REPORT.duration_s, " s"));
    text("frames", String(REPORT.frame_count));
    text("outages", `${REPORT.connection_outages} / ${REPORT.recoveries}`);
    text("outage-duration", fmt(REPORT.max_connection_outage_s, " s"));
    text("intervals", `${fmt(REPORT.frame_interval_p50_s, " s")} / ${fmt(REPORT.frame_interval_p95_s, " s")}`);
    text("gap", fmt(REPORT.max_frame_gap_s, " s"));
    text("profiles", REPORT.profiles.join(", ") || "não informado");
    text("verified", REPORT.verified_states.join(", ") || "não informado");
    for (const payload of REPORT.raw_payloads) {
      const item = document.createElement("li");
      const code = document.createElement("code");
      code.textContent = payload;
      item.append(code);
      $("raw-payloads").append(item);
    }

    const records = REPORT.frames;
    const start = records.length ? records[0].ts : 0;
    const end = records.length ? records[records.length - 1].ts : start;
    const span = Math.max(end - start, 1);
    const gaps = records.slice(1).map((frame, index) => frame.ts - records[index].ts).filter((v) => v > 0);
    const gapThreshold = gaps.length ? Math.max(1, 3 * gaps.slice().sort((a, b) => a - b)[Math.floor((gaps.length - 1) / 2)]) : Infinity;
    const available = Object.keys(SIGNALS).filter((key) =>
      records.some((frame) => frame.conn && frame.lid_available &&
        typeof frame.values[key] === "number" && Number.isFinite(frame.values[key])));

    function makeChart(key, index) {
      const [label, unit] = SIGNALS[key];
      const section = document.createElement("article");
      section.className = "chart";
      const heading = document.createElement("h2");
      heading.textContent = `${label} (${unit})`;
      section.append(heading);
      const values = records.map((frame) => frame.conn && frame.lid_available ? frame.values[key] : null)
        .filter((value) => typeof value === "number" && Number.isFinite(value));
      if (!values.length) {
        const empty = document.createElement("p");
        empty.className = "empty";
        empty.textContent = "Sem amostras disponíveis para este sinal.";
        section.append(empty);
        return section;
      }
      let min = values.reduce((current, value) => Math.min(current, value), Infinity);
      let max = values.reduce((current, value) => Math.max(current, value), -Infinity);
      if (min === max) {
        const padding = Math.max(Math.abs(min) * 0.05, 1);
        min -= padding;
        max += padding;
      }
      const width = 900, height = 250, left = 70, right = 18, top = 14, bottom = 38;
      const plotWidth = width - left - right, plotHeight = height - top - bottom;
      const x = (ts) => left + ((ts - start) / span) * plotWidth;
      const y = (value) => top + ((max - value) / (max - min)) * plotHeight;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", `Gráfico temporal de ${label}`);
      for (let tick = 0; tick <= 4; tick += 1) {
        const value = min + (max - min) * tick / 4;
        const yy = y(value);
        const grid = document.createElementNS(svg.namespaceURI, "line");
        grid.setAttribute("x1", String(left)); grid.setAttribute("x2", String(width - right));
        grid.setAttribute("y1", String(yy)); grid.setAttribute("y2", String(yy));
        grid.setAttribute("class", "gridline"); svg.append(grid);
        const labelNode = document.createElementNS(svg.namespaceURI, "text");
        labelNode.setAttribute("x", String(left - 8)); labelNode.setAttribute("y", String(yy + 4));
        labelNode.setAttribute("text-anchor", "end"); labelNode.setAttribute("class", "tick");
        labelNode.textContent = value.toFixed(2); svg.append(labelNode);
      }
      const axis = document.createElementNS(svg.namespaceURI, "line");
      axis.setAttribute("x1", String(left)); axis.setAttribute("x2", String(left));
      axis.setAttribute("y1", String(top)); axis.setAttribute("y2", String(height - bottom));
      axis.setAttribute("class", "axis"); svg.append(axis);
      const xAxis = document.createElementNS(svg.namespaceURI, "line");
      xAxis.setAttribute("x1", String(left)); xAxis.setAttribute("x2", String(width - right));
      xAxis.setAttribute("y1", String(height - bottom)); xAxis.setAttribute("y2", String(height - bottom));
      xAxis.setAttribute("class", "axis"); svg.append(xAxis);
      for (let tick = 0; tick <= 4; tick += 1) {
        const xx = left + plotWidth * tick / 4;
        const labelNode = document.createElementNS(svg.namespaceURI, "text");
        labelNode.setAttribute("x", String(xx)); labelNode.setAttribute("y", String(height - 12));
        labelNode.setAttribute("text-anchor", "middle"); labelNode.setAttribute("class", "tick");
        labelNode.textContent = `${((end - start) * tick / 4).toFixed(1)} s`; svg.append(labelNode);
      }
      let path = "", drawing = false, priorTs = null;
      for (const frame of records) {
        const value = frame.conn && frame.lid_available ? frame.values[key] : null;
        const valid = typeof value === "number" && Number.isFinite(value);
        if (!valid || (priorTs !== null && frame.ts - priorTs > gapThreshold)) {
          drawing = false;
        }
        if (valid) {
          path += `${drawing ? "L" : "M"}${x(frame.ts).toFixed(2)},${y(value).toFixed(2)} `;
          const point = document.createElementNS(svg.namespaceURI, "circle");
          point.setAttribute("cx", String(x(frame.ts)));
          point.setAttribute("cy", String(y(value)));
          point.setAttribute("r", "2.5");
          point.setAttribute("fill", COLORS[index % COLORS.length]);
          point.setAttribute("aria-label", `${label}: ${value} ${unit}`);
          const pointTitle = document.createElementNS(svg.namespaceURI, "title");
          pointTitle.textContent = `${((frame.ts - start)).toFixed(3)} s: ${value} ${unit}`;
          point.append(pointTitle);
          svg.append(point);
          drawing = true;
        }
        priorTs = frame.ts;
      }
      const line = document.createElementNS(svg.namespaceURI, "path");
      line.setAttribute("d", path.trim());
      line.setAttribute("class", "series");
      line.setAttribute("stroke", COLORS[index % COLORS.length]);
      svg.append(line);
      section.append(svg);
      const gapNote = document.createElement("p");
      gapNote.className = "gap";
      gapNote.textContent = `Amostras válidas: ${values.length}. Segmentos são separados em falhas, LID ausente, valor ausente ou intervalo > ${gapThreshold === Infinity ? "∞" : gapThreshold.toFixed(3)} s.`;
      section.append(gapNote);
      return section;
    }

    const options = $("signal-options");
    if (!available.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Esta captura não contém valores decodificados para plotar. Os payloads crus permanecem disponíveis no relatório.";
      options.append(empty);
    } else {
      available.forEach((key, index) => {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox"; checkbox.checked = true;
        checkbox.addEventListener("change", () => {
          const chart = document.getElementById(`chart-${key}`);
          if (chart) chart.hidden = !checkbox.checked;
        });
        label.append(checkbox, ` ${SIGNALS[key][0]}`);
        options.append(label);
        const chart = makeChart(key, index);
        chart.id = `chart-${key}`;
        $("charts").append(chart);
      });
    }
  </script>
</body>
</html>
"""

COMPARISON_TEMPLATE = """<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Comparação de capturas — NissanScan</title>
  <style>
    :root { color-scheme: light; font-family: system-ui, sans-serif; color: #17212b; background: #f2f5f8; }
    * { box-sizing: border-box; }
    body { max-width: 1200px; margin: 0 auto; padding: 24px; }
    .notice, .meta, .chart { border: 1px solid #d2dbe5; background: white; border-radius: 8px; padding: 14px; }
    .notice { border-left: 4px solid #dc9c28; margin: 16px 0; }
    .meta { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px 18px; }
    .meta div { overflow-wrap: anywhere; }
    fieldset { display: flex; flex-wrap: wrap; gap: 8px 16px; border: 1px solid #d2dbe5; border-radius: 8px; margin: 18px 0; }
    .chart { margin: 14px 0; overflow: hidden; }
    svg { display: block; width: 100%; height: 260px; }
    .axis { stroke: #6f7e8d; stroke-width: 1; }
    .gridline { stroke: #e1e7ed; stroke-width: 1; }
    .tick { fill: #465565; font-size: 12px; }
    .legend { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0; }
    .legend span { border-left: 4px solid; padding-left: 7px; }
    .empty { color: #687789; padding: 36px 10px; text-align: center; }
    [hidden] { display: none !important; }
    @media (max-width: 650px) { body { padding: 12px; } svg { height: 220px; } }
  </style>
</head>
<body>
  <h1>Comparação offline de capturas</h1>
  <p>Somente leitura. Cada captura é alinhada ao seu próprio primeiro frame (tempo decorrido);
    não há sincronização absoluta nem interpretação dos payloads crus.</p>
  <div id="warnings" class="notice" role="status"></div>
  <section id="capture-metadata" class="meta" aria-label="Capturas comparadas"></section>
  <fieldset>
    <legend>Sinais presentes nas duas capturas</legend>
    <div id="signal-options"></div>
  </fieldset>
  <section id="charts" aria-live="polite"></section>
  <script>
    const COMPARISON = __COMPARISON_DATA__;
    const SIGNALS = __SIGNAL_DATA__;
    const COLORS = ["#1479bd", "#d16b16"];
    const $ = (id) => document.getElementById(id);
    const metadataKeys = [
      ["Veículo", "vehicle"], ["ECU", "ecu"], ["Perfil do veículo", "vehicle_profile"],
      ["Adaptador", "adapter"], ["Validação", "validation_status"],
    ];
    COMPARISON.captures.forEach((capture, captureIndex) => {
      const card = document.createElement("div");
      const heading = document.createElement("strong");
      heading.textContent = `Captura ${captureIndex === 0 ? "A" : "B"} — ${capture.label}`;
      card.append(heading, document.createElement("br"));
      for (const [label, key] of metadataKeys) {
        const row = document.createElement("div");
        row.textContent = `${label}: ${capture.metadata[key] || "não registrado"}`;
        card.append(row);
      }
      const decoderProfiles = document.createElement("div");
      decoderProfiles.textContent = `Perfil(is) do decoder: ${capture.decoder_profiles.join(", ") || "não informado"}`;
      card.append(decoderProfiles);
      const verifiedStates = document.createElement("div");
      verifiedStates.textContent = `verified nos frames: ${capture.verified_states.join(", ") || "não informado"}`;
      card.append(verifiedStates);
      const details = document.createElement("div");
      details.textContent = `Início: ${capture.started_at}; frames: ${capture.frame_count}; captura ${capture.complete ? "completa" : "incompleta"}`;
      card.append(details);
      $("capture-metadata").append(card);
    });
    const differences = [];
    for (const [, key] of metadataKeys) {
      const first = COMPARISON.captures[0].metadata[key];
      const second = COMPARISON.captures[1].metadata[key];
      if ((first || null) !== (second || null)) differences.push(key);
    }
    if (JSON.stringify(COMPARISON.captures[0].decoder_profiles) !==
        JSON.stringify(COMPARISON.captures[1].decoder_profiles)) {
      differences.push("perfil do decoder");
    }
    if (JSON.stringify(COMPARISON.captures[0].verified_states) !==
        JSON.stringify(COMPARISON.captures[1].verified_states)) {
      differences.push("estado verified");
    }
    $("warnings").textContent = differences.length
      ? `Atenção: diferenças detectadas (${differences.join(", ")}). Confirme que veículo, ECU e perfis são comparáveis antes de interpretar as curvas.`
      : "Mesmo metadado não prova equivalência de veículo, sessão, decoder ou condições de teste. Valores e escalas permanecem hipóteses.";

    const commonSignals = Object.keys(SIGNALS).filter((key) =>
      COMPARISON.captures.every((capture) =>
        capture.frames.some((frame) => frame.conn && frame.lid_available &&
          typeof frame.values[key] === "number" && Number.isFinite(frame.values[key]))));
    const allTimes = COMPARISON.captures.flatMap((capture) =>
      capture.frames.map((frame) => frame.elapsed_s));
    const timeEnd = Math.max(...allTimes, 1);
    const gaps = COMPARISON.captures.map((capture) => {
      const intervals = capture.frames.slice(1).map((frame, index) =>
        frame.elapsed_s - capture.frames[index].elapsed_s).filter((value) => value > 0)
        .sort((a, b) => a - b);
      const median = intervals.length
        ? intervals[Math.floor((intervals.length - 1) / 2)] : Infinity;
      return Math.max(1, median * 3);
    });

    function makeChart(key) {
      const [label, unit] = SIGNALS[key];
      const article = document.createElement("article");
      article.className = "chart";
      const heading = document.createElement("h2");
      heading.textContent = `${label} (${unit})`;
      article.append(heading);
      const validValues = COMPARISON.captures.flatMap((capture) =>
        capture.frames.filter((frame) => frame.conn && frame.lid_available)
          .map((frame) => frame.values[key])
          .filter((value) => typeof value === "number" && Number.isFinite(value)));
      let min = Math.min(...validValues), max = Math.max(...validValues);
      if (min === max) {
        const padding = Math.max(Math.abs(min) * 0.05, 1);
        min -= padding; max += padding;
      }
      const width = 900, height = 250, left = 70, right = 18, top = 14, bottom = 38;
      const plotWidth = width - left - right, plotHeight = height - top - bottom;
      const x = (elapsed) => left + (elapsed / timeEnd) * plotWidth;
      const y = (value) => top + ((max - value) / (max - min)) * plotHeight;
      const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      svg.setAttribute("role", "img");
      svg.setAttribute("aria-label", `Comparação temporal de ${label}`);
      for (let tick = 0; tick <= 4; tick += 1) {
        const yy = top + plotHeight * tick / 4;
        const grid = document.createElementNS(svg.namespaceURI, "line");
        grid.setAttribute("x1", String(left)); grid.setAttribute("x2", String(width - right));
        grid.setAttribute("y1", String(yy)); grid.setAttribute("y2", String(yy));
        grid.setAttribute("class", "gridline"); svg.append(grid);
        const tickLabel = document.createElementNS(svg.namespaceURI, "text");
        tickLabel.setAttribute("x", String(left - 8)); tickLabel.setAttribute("y", String(yy + 4));
        tickLabel.setAttribute("text-anchor", "end"); tickLabel.setAttribute("class", "tick");
        tickLabel.textContent = (max - (max - min) * tick / 4).toFixed(2); svg.append(tickLabel);
      }
      const xAxis = document.createElementNS(svg.namespaceURI, "line");
      xAxis.setAttribute("x1", String(left)); xAxis.setAttribute("x2", String(width - right));
      xAxis.setAttribute("y1", String(height - bottom)); xAxis.setAttribute("y2", String(height - bottom));
      xAxis.setAttribute("class", "axis"); svg.append(xAxis);
      for (let tick = 0; tick <= 4; tick += 1) {
        const tickLabel = document.createElementNS(svg.namespaceURI, "text");
        tickLabel.setAttribute("x", String(left + plotWidth * tick / 4));
        tickLabel.setAttribute("y", String(height - 12));
        tickLabel.setAttribute("text-anchor", "middle"); tickLabel.setAttribute("class", "tick");
        tickLabel.textContent = `${(timeEnd * tick / 4).toFixed(1)} s`; svg.append(tickLabel);
      }
      const legend = document.createElement("div");
      legend.className = "legend";
      COMPARISON.captures.forEach((capture, captureIndex) => {
        const item = document.createElement("span");
        item.style.borderColor = COLORS[captureIndex];
        item.textContent = capture.label;
        legend.append(item);
        let path = "", drawing = false, priorTime = null, validCount = 0;
        for (const frame of capture.frames) {
          const value = frame.conn && frame.lid_available ? frame.values[key] : null;
          const valid = typeof value === "number" && Number.isFinite(value);
          if (!valid || (priorTime !== null && frame.elapsed_s - priorTime > gaps[captureIndex])) {
            drawing = false;
          }
          if (valid) {
            const px = x(frame.elapsed_s), py = y(value);
            path += `${drawing ? "L" : "M"}${px.toFixed(2)},${py.toFixed(2)} `;
            const point = document.createElementNS(svg.namespaceURI, "circle");
            point.setAttribute("cx", String(px)); point.setAttribute("cy", String(py));
            point.setAttribute("r", "2.5"); point.setAttribute("fill", COLORS[captureIndex]);
            const title = document.createElementNS(svg.namespaceURI, "title");
            title.textContent = `${capture.label} — ${frame.elapsed_s.toFixed(3)} s: ${value} ${unit}`;
            point.append(title); svg.append(point);
            drawing = true; validCount += 1;
          }
          priorTime = frame.elapsed_s;
        }
        const line = document.createElementNS(svg.namespaceURI, "path");
        line.setAttribute("d", path.trim()); line.setAttribute("fill", "none");
        line.setAttribute("stroke", COLORS[captureIndex]); line.setAttribute("stroke-width", "2");
        line.setAttribute("vector-effect", "non-scaling-stroke"); svg.append(line);
        item.title = `${validCount} amostras válidas`;
      });
      article.append(legend, svg);
      return article;
    }
    if (!commonSignals.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "Não há sinais numéricos em comum nas duas capturas para comparar.";
      $("signal-options").append(empty);
    } else {
      commonSignals.forEach((key) => {
        const label = document.createElement("label");
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox"; checkbox.checked = true;
        const chart = makeChart(key);
        chart.id = `chart-${key}`;
        checkbox.addEventListener("change", () => { chart.hidden = !checkbox.checked; });
        label.append(checkbox, ` ${SIGNALS[key][0]}`);
        $("signal-options").append(label);
        $("charts").append(chart);
      });
    }
  </script>
</body>
</html>
"""


def _read_capture_frames(capture_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summary = summarize_capture(capture_path)
    records: list[dict[str, Any]] = []
    previous_timestamp: float | None = None
    with capture_path.open(encoding="utf-8") as capture_file:
        for line_number, line in enumerate(capture_file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if record["event"] != "frame":
                continue
            frame = record["frame"]
            timestamp = frame.get("ts")
            if (
                isinstance(timestamp, bool)
                or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)
            ):
                raise ValueError(f"linha {line_number}: frame.ts deve ser timestamp Unix finito")
            if previous_timestamp is not None and timestamp < previous_timestamp:
                raise ValueError(f"linha {line_number}: frame.ts fora de ordem")
            previous_timestamp = timestamp
            if not isinstance(frame.get("conn"), bool) or not isinstance(frame.get("lid_available"), bool):
                raise ValueError(f"linha {line_number}: conn e lid_available devem ser boolean")
            values: dict[str, float | None] = {}
            for signal in SIGNALS:
                value = frame.get(signal)
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value)
                ):
                    raise ValueError(f"linha {line_number}: campo {signal} deve ser numérico finito")
                values[signal] = value
            records.append({
                "ts": timestamp,
                "conn": frame["conn"],
                "lid_available": frame["lid_available"],
                "values": values,
                "raw_lid01": frame.get("raw_lid01"),
                "profile": frame.get("profile"),
                "verified": frame.get("verified"),
                "data_source": frame.get("data_source"),
                "error": frame.get("error"),
                "decode_error": frame.get("decode_error"),
            })
    return summary, records


def _csv_rows(summary: dict[str, Any], frames: list[dict[str, Any]]):
    metadata = summary["metadata"]
    start = datetime.fromisoformat(summary["started_at"])

    def safe_text(value: Any) -> Any:
        if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + value
        return value

    for frame in frames:
        timestamp = datetime.fromtimestamp(frame["ts"], tz=timezone.utc)
        row: dict[str, Any] = {
            "timestamp_utc": timestamp.isoformat(),
            "elapsed_s": round((timestamp - start).total_seconds(), 3),
            "vehicle": safe_text(metadata.get("vehicle", "")),
            "ecu": safe_text(metadata.get("ecu", "")),
            "adapter": safe_text(metadata.get("adapter", "")),
            "vehicle_profile": safe_text(metadata.get("vehicle_profile", "")),
            "data_source": safe_text(frame.get("data_source", "")),
            "conn": frame["conn"],
            "lid_available": frame["lid_available"],
            "raw_lid01_hex": safe_text(frame.get("raw_lid01") or ""),
            "profile": safe_text(frame.get("profile", "")),
            "verified": safe_text(frame.get("verified", "")),
            "error": safe_text(frame.get("error", "")),
            "decode_error": safe_text(frame.get("decode_error", "")),
        }
        row.update({signal: frame["values"][signal] for signal in SIGNALS})
        yield row


def export_capture_csv(capture_path: Path, output_path: Path) -> int:
    summary, frames = _read_capture_frames(capture_path)
    with output_path.open("x", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in _csv_rows(summary, frames):
            writer.writerow(row)
    return len(frames)


def generate_capture_report(capture_path: Path, output_path: Path) -> int:
    summary, frames = _read_capture_frames(capture_path)
    report_data = {
        "metadata": summary["metadata"],
        "started_at": summary["started_at"],
        "complete": summary["complete"],
        "duration_s": summary["duration_s"],
        "frame_count": summary["frame_count"],
        "connection_outages": summary["connection_outages"],
        "recoveries": summary["recoveries"],
        "max_connection_outage_s": summary["max_connection_outage_s"],
        "frame_interval_p50_s": summary["frame_interval_p50_s"],
        "frame_interval_p95_s": summary["frame_interval_p95_s"],
        "max_frame_gap_s": summary["max_frame_gap_s"],
        "raw_payloads": summary["raw_lid01_payloads"],
        "profiles": sorted({frame["profile"] for frame in frames if frame["profile"]}),
        "verified_states": sorted(
            {str(frame["verified"]) for frame in frames if frame["verified"] is not None}
        ),
        "frames": frames,
    }
    embedded_data = json.dumps(report_data, ensure_ascii=False, allow_nan=False)
    embedded_data = (
        embedded_data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    embedded_signals = json.dumps(SIGNALS, ensure_ascii=False).replace("<", "\\u003c")
    html = HTML_TEMPLATE.replace("__SIGNALS__", embedded_signals).replace(
        "__REPORT_DATA__", embedded_data,
    )
    with output_path.open("x", encoding="utf-8", newline="\n") as report_file:
        report_file.write(html)
    return len(frames)


def generate_capture_comparison_report(
    first_capture_path: Path,
    second_capture_path: Path,
    output_path: Path,
) -> tuple[int, int]:
    first_summary, first_frames = _read_capture_frames(first_capture_path)
    second_summary, second_frames = _read_capture_frames(second_capture_path)
    captures = []
    for capture_path, summary, frames in (
        (first_capture_path, first_summary, first_frames),
        (second_capture_path, second_summary, second_frames),
    ):
        first_timestamp = frames[0]["ts"] if frames else 0.0
        captures.append({
            "label": capture_path.name,
            "metadata": summary["metadata"],
            "started_at": summary["started_at"],
            "complete": summary["complete"],
            "frame_count": summary["frame_count"],
            "decoder_profiles": sorted({
                frame["profile"] for frame in frames if frame["profile"]
            }),
            "verified_states": sorted({
                str(frame["verified"])
                for frame in frames if frame["verified"] is not None
            }),
            "frames": [
                {
                    "elapsed_s": frame["ts"] - first_timestamp,
                    "conn": frame["conn"],
                    "lid_available": frame["lid_available"],
                    "values": frame["values"],
                }
                for frame in frames
            ],
        })
    comparison_data = json.dumps(
        {"captures": captures},
        ensure_ascii=False,
        allow_nan=False,
    )
    comparison_data = (
        comparison_data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    signal_data = json.dumps(SIGNALS, ensure_ascii=False).replace("<", "\\u003c")
    html = COMPARISON_TEMPLATE.replace("__SIGNAL_DATA__", signal_data).replace(
        "__COMPARISON_DATA__", comparison_data,
    )
    with output_path.open("x", encoding="utf-8", newline="\n") as report_file:
        report_file.write(html)
    return len(first_frames), len(second_frames)
