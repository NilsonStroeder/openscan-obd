"""
field_tests.py — Testes de campo para decodificação do LID 0x01 do TCM CVT
Nissan Sentra B16 2010 / JF011E / RE0F10A

Uso:
    python field_tests.py <label>

Labels disponíveis:
    frio              — Carro frio antes de ligar (ATF TEMP lookup)
    P / N / D / R     — Posição do seletor (RANGE SW, GEAR RATIO)
    rpm1000/2000/3000 — RPM fixos em P (PRI SPEED scale + SEC SPEED)
    accel25/50/75/100 — Acelerador em % (ACC PEDAL POS)
    cruising60/80/100 — Velocidade constante em D (GEAR RATIO)
    arranque          — Arrancada suave D (SLIP REV)
    tcc               — Lock-up engajado em alta (TCC SLIP REV = 0)

Cada label captura o LID 0x01 e imprime a análise automática dos bytes de interesse.
"""

import sys
import struct
import json
import datetime

# ─── ATF TEMP lookup table (Nissan ESM, não-linear) ──────────────────────────
ATF_TABLE = [
    (4,   -30), (47,  20), (83,  40), (124, 60),
    (169,  85), (243, 200),
]

def atf_count_to_celsius(count: int) -> float:
    if count <= ATF_TABLE[0][0]:
        return float(ATF_TABLE[0][1])
    if count >= ATF_TABLE[-1][0]:
        return float(ATF_TABLE[-1][1])
    for i in range(len(ATF_TABLE) - 1):
        c0, t0 = ATF_TABLE[i]
        c1, t1 = ATF_TABLE[i + 1]
        if c0 <= count <= c1:
            return t0 + (t1 - t0) * (count - c0) / (c1 - c0)
    return float("nan")


# ─── Parser do payload LID 0x01 ──────────────────────────────────────────────
def parse_lid01(payload: bytes) -> dict:
    """
    payload: 69 bytes (byte[0] = echo LID = 0x01, dados em [1]..[68])
    Retorna dict com grandezas decodificadas (algumas como hipótese).
    """
    assert len(payload) == 69, f"Esperado 69 bytes, recebido {len(payload)}"
    b = payload  # índice direto

    # PRI SPEED — bytes[6,7] WORD BE ÷ 8
    pri_speed_raw = (b[6] << 8) | b[7]
    pri_speed_rpm = pri_speed_raw / 8.0

    # SEC SPEED (hipótese) — byte[15], escala a confirmar
    # Em P idle = mesmo que PRI; em cruising deve divergir
    sec_byte15 = b[15]

    # ATF TEMP — byte[9] lookup não-linear
    atf_count = b[9]
    atf_temp_c = atf_count_to_celsius(atf_count)

    # Coolant via CAN (hipótese) — byte[10], mesma lookup?
    coolant_count = b[10]
    coolant_hyp_c = atf_count_to_celsius(coolant_count)  # hipótese — mesma tabela?

    # ACC PEDAL POS (hipótese) — bytes[19-22], escala a confirmar
    acc_bytes = [b[19], b[20], b[21], b[22]]

    # CLOSED THL/SW ou RANGE SW (hipótese) — byte[23]
    byte23 = b[23]

    # Flags independentes (hipótese) — bytes[25,26]
    flag25 = b[25]
    flag26 = b[26]

    # GEAR RATIO ou STM STEP (hipótese) — bytes[36,37] WORD BE
    word3637 = (b[36] << 8) | b[37]
    # Tentativas de conversão (nenhuma confirmada):
    ratio_hyp = word3637 / 10000.0          # se for ratio ×10000
    step_hyp  = word3637 / 96.0             # se for step ×96

    # SLIP REV (hipótese) — bytes[38,39]
    # 0xFE = inativo (lock-up desengajado / não calculado)
    slip38 = b[38]
    slip39 = b[39]
    slip_inactive = (slip38 == 0xFE)

    # LINE PRS S/V (hipótese) — bytes[44,45] WORD LE
    line_cmd_raw = struct.unpack_from("<H", b, 44)[0]

    # SEC PRES (hipótese) — bytes[46,47] WORD LE
    sec_pres_raw = struct.unpack_from("<H", b, 46)[0]
    sec_pres_mpa = sec_pres_raw / 1000.0    # hipótese

    # bytes[48,49] e [50,51] — possivelmente target vs actual
    word4849 = struct.unpack_from("<H", b, 48)[0]
    word5051 = struct.unpack_from("<H", b, 50)[0]

    return {
        "pri_speed_rpm":    pri_speed_rpm,
        "atf_temp_c":       atf_temp_c,
        "atf_count":        atf_count,
        "coolant_count":    coolant_count,
        "coolant_hyp_c":    coolant_hyp_c,
        "sec_byte15":       sec_byte15,
        "acc_bytes":        acc_bytes,
        "byte23":           byte23,
        "flag25":           flag25,
        "flag26":           flag26,
        "word3637":         word3637,
        "ratio_hyp":        ratio_hyp,
        "step_hyp":         step_hyp,
        "slip38":           slip38,
        "slip39":           slip39,
        "slip_inactive":    slip_inactive,
        "line_cmd_raw":     line_cmd_raw,
        "sec_pres_raw":     sec_pres_raw,
        "sec_pres_mpa":     sec_pres_mpa,
        "word4849":         word4849,
        "word5051":         word5051,
        "raw_b23":          b[23],
        "raw_b25":          b[25],
        "raw_b26":          b[26],
    }


# ─── Impressão contextualizada por cenário ────────────────────────────────────
SEPARATOR = "─" * 60

def print_header(label: str):
    print(SEPARATOR)
    print(f"  CAMPO: {label}  |  {datetime.datetime.now().isoformat(timespec='seconds')}")
    print(SEPARATOR)


def analyze_frio(p: dict):
    print_header("CARRO FRIO — ATF TEMP lookup")
    print(f"  byte[9]  ATF COUNT     = {p['atf_count']}  →  {p['atf_temp_c']:.1f}°C")
    print(f"  byte[10] COOLANT COUNT = {p['coolant_count']}  (hipótese →  {p['coolant_hyp_c']:.1f}°C)")
    print()
    if p["atf_count"] < 47:
        print("  ✅ ATF < 20°C — lookup table provavelmente correta")
    elif p["atf_count"] < 83:
        print("  🟡 ATF entre 20–40°C — lookup coerente")
    else:
        print("  ⚠️  ATF > 40°C — motor não estava suficientemente frio")
    print()
    print("  INTERPRETAÇÃO byte[10]:")
    print(f"    Se coolant ≈ temperatura ambiente → mesma lookup → confirma coolant via CAN")
    print(f"    Se coolant >> ATF → byte[10] é outra coisa")


def analyze_selector(p: dict, label: str):
    print_header(f"SELETOR — {label}")
    print(f"  byte[23]  = {p['byte23']}  (hex: {p['byte23']:02X})")
    print(f"  byte[25]  = {p['flag25']}  (hex: {p['flag25']:02X})")
    print(f"  byte[26]  = {p['flag26']}  (hex: {p['flag26']:02X})")
    print()
    print("  Referências (colete para todos P/N/D/R e compare):")
    print("    Se byte[23] muda com P/N/D/R → é RANGE SW")
    print("    Se byte[23] só muda com acelerador → é CLOSED THL/SW")
    print("    Se byte[23] muda apenas D↔P → pode ser embreagem forward")
    print()
    print(f"  bytes[36,37] WORD BE = {p['word3637']}")
    print(f"    hipótese GEAR RATIO = {p['ratio_hyp']:.4f}")
    print(f"    hipótese STM STEP   = {p['step_hyp']:.1f}")
    print()
    print("  ESPERADO:")
    print("    P/N: ratio ≈ 2.34 (LOW) → word3637 ≈ 23400 se ×10000")
    print("    R:   ratio ≈ 1.75 fixo  → word3637 ≈ 17500")


def analyze_rpm(p: dict, label: str):
    print_header(f"RPM FIXO — {label}")
    print(f"  bytes[6,7]  PRI SPEED  = {p['pri_speed_rpm']:.0f} rpm  (raw WORD BE = {int(p['pri_speed_rpm']*8)})")
    print(f"  byte[15]    SEC cand.  = {p['sec_byte15']}  (×32 → {p['sec_byte15']*32} rpm)")
    print()
    if abs(p['sec_byte15'] * 32 - p['pri_speed_rpm']) < 50:
        print("  byte[15] ≈ PRI — câmbio em P (polias livres) → coerente")
    else:
        print(f"  byte[15] DIVERGE de PRI → byte[15] provavelmente não é espelho simples")
    print()
    print("  VERIFIQUE: RPM no painel vs pri_speed_rpm — diff < 50 rpm confirma escala ÷8")


def analyze_accel(p: dict, label: str):
    print_header(f"ACELERADOR — {label}")
    print(f"  bytes[19-22] = {p['acc_bytes']}  (valores brutos)")
    print()
    acc_val = p['acc_bytes'][0]
    print(f"  byte[19] = {acc_val}")
    print(f"    se escala oitavos: {acc_val}/8 = {acc_val/8:.2f} → {acc_val/8*100:.0f}%")
    print(f"    se escala 0-100:   {acc_val}%")
    print(f"    se escala 0-255:   {acc_val/255*100:.0f}%")
    print()
    print("  COLETA: posição acelerador anotada manualmente + valor byte[19]")
    print("  Exemplo: pedal solto=0, leve≈10%, médio≈50%, fundo≈100%")
    print("  3 pontos determinam a escala")


def analyze_cruising(p: dict, label: str):
    print_header(f"CRUISING — {label}")
    print(f"  bytes[36,37] WORD BE = {p['word3637']}")
    print(f"    hipótese GEAR RATIO = {p['ratio_hyp']:.4f}")
    print(f"    hipótese STM STEP   = {p['step_hyp']:.1f}")
    print()
    print(f"  pri_speed_rpm = {p['pri_speed_rpm']:.0f} rpm")
    print(f"  byte[15]      = {p['sec_byte15']}  (×32 = {p['sec_byte15']*32} rpm)")
    if p['sec_byte15'] > 0:
        ratio_from_speeds = p['pri_speed_rpm'] / (p['sec_byte15'] * 32)
        print(f"  RATIO calculado de velocidades = {ratio_from_speeds:.3f}:1")
        print(f"  Se word3637 ÷ 10000 = {p['ratio_hyp']:.4f} e ratio_speeds = {ratio_from_speeds:.3f}:")
        if abs(p['ratio_hyp'] - ratio_from_speeds) < 0.1:
            print("  ✅ MATCH — bytes[36,37] provavelmente é GEAR RATIO")
        else:
            print("  ❌ Sem match — escala incorreta ou grandeza diferente")
    print()
    print("  ESPERADO cruising estável:")
    print("    60 km/h D → ratio ≈ 0.8–1.2:1 → word3637 ≈ 8000–12000 se ×10000")
    print("    80 km/h D → ratio ≈ 0.5–0.8:1 → word3637 ≈ 5000–8000")


def analyze_arranque(p: dict):
    print_header("ARRANQUE SUAVE — SLIP REV")
    print(f"  byte[38] = {p['slip38']:3d}  (hex: {p['slip38']:02X})  {'← INATIVO (0xFE)' if p['slip38']==0xFE else ''}")
    print(f"  byte[39] = {p['slip39']:3d}  (hex: {p['slip39']:02X})  {'← INATIVO (0xFE)' if p['slip39']==0xFE else ''}")
    print()
    if p['slip_inactive']:
        print("  Lock-up desengajado ou TCM não calcula slip → 0xFE = inativo")
    else:
        print(f"  SLIP ativo: byte[38]={p['slip38']} → possível SLIP REV = {p['slip38']} rpm")
        print(f"              (se fórmula = valor direto em rpm)")
    print()
    print("  SEQUÊNCIA DE COLETA:")
    print("    1. Parado em D   → bytes[38,39] = 0xFE (esperado)")
    print("    2. Arrancada leve → bytes saem de 0xFE (lock-up abre)")
    print("    3. Velocidade constante → bytes voltam próximo de 0 (lock-up fecha)")
    print("    Se padrão acima = SLIP REV confirmado conceitualmente")


def analyze_tcc(p: dict):
    print_header("TCC LOCK-UP — SLIP REV próximo de 0")
    print(f"  byte[38] = {p['slip38']:3d}  (hex: {p['slip38']:02X})")
    print(f"  byte[39] = {p['slip39']:3d}  (hex: {p['slip39']:02X})")
    print(f"  pri_speed_rpm = {p['pri_speed_rpm']:.0f} rpm")
    print()
    if 0 < p['slip38'] < 10:
        print("  ✅ Valor baixo → TCC provavelmente engajado (SLIP REV ≈ 0)")
    elif p['slip38'] == 0xFE:
        print("  ⚠️  0xFE — TCM marca como inativo. Lock-up possivelmente ainda não engajou")
        print("      Aumente velocidade ou mantenha carga constante por mais tempo")
    else:
        print(f"  🔴 Valor {p['slip38']} — slip ativo ou grandeza diferente")
    print()
    print("  REFERÊNCIA ESM P0744: em lock-up engajado SLIP REV ≈ 0 rpm")


# ─── Dispatcher ───────────────────────────────────────────────────────────────
USAGE = """
Uso: python field_tests.py <label> [hex_payload]

Labels:
  frio              Carro frio — ATF TEMP lookup
  P / N / D / R     Seletor de marcha — RANGE SW / GEAR RATIO
  rpm1000           RPM fixo 1000 — escala PRI SPEED
  rpm2000           RPM fixo 2000
  rpm3000           RPM fixo 3000
  accel25           Acelerador 25%
  accel50           Acelerador 50%
  accel75           Acelerador 75%
  accel100          Acelerador fundo
  cruising60        Velocidade constante 60 km/h em D
  cruising80        Velocidade constante 80 km/h em D
  cruising100       Velocidade constante 100 km/h em D
  arranque          Arrancada suave em D
  tcc               Lock-up engajado em alta velocidade

Payload:
  69 bytes em hex separados por espaço.
  Se omitido, usa o payload de referência (marcha_lenta).
"""

# Payload de referência (marcha_lenta do snapshot)
REFERENCE_PAYLOAD_HEX = (
    "01 00 00 01 00 01 16 3A 00 7C B2 00 08 02 02 16 7F EB 00 00 00 00 00 01 01 01 03 "
    "7E 25 00 83 24 C8 2D 2D D8 42 26 FE FE FE 02 78 02 A0 02 6D 02 76 02 A0 02 6D 00 "
    "11 00 00 00 01 00 0A 11 12 03 00 06 00 00 5F"
)

ANALYZERS = {
    "frio":       lambda p: analyze_frio(p),
    "p":          lambda p: analyze_selector(p, "P"),
    "n":          lambda p: analyze_selector(p, "N"),
    "d":          lambda p: analyze_selector(p, "D"),
    "r":          lambda p: analyze_selector(p, "R"),
    "rpm1000":    lambda p: analyze_rpm(p, "1000 rpm"),
    "rpm2000":    lambda p: analyze_rpm(p, "2000 rpm"),
    "rpm3000":    lambda p: analyze_rpm(p, "3000 rpm"),
    "accel25":    lambda p: analyze_accel(p, "25%"),
    "accel50":    lambda p: analyze_accel(p, "50%"),
    "accel75":    lambda p: analyze_accel(p, "75%"),
    "accel100":   lambda p: analyze_accel(p, "100% (fundo)"),
    "cruising60": lambda p: analyze_cruising(p, "60 km/h D"),
    "cruising80": lambda p: analyze_cruising(p, "80 km/h D"),
    "cruising100":lambda p: analyze_cruising(p, "100 km/h D"),
    "arranque":   lambda p: analyze_arranque(p),
    "tcc":        lambda p: analyze_tcc(p),
}


HYPOTHESIS_WARNING = (
    "  AVISO: as interpretações abaixo são de 2026-10-23. ATF [9], RANGE SW\n"
    "  [23-25] e STM [36,37] foram rebaixados para hipótese em 2026-11-05\n"
    "  (docs/scanner_params_tracker.md). Use o payload cru como referência."
)


def run_analysis(scenario: str, payload: bytes, label: str | None = None) -> dict:
    """Analisa um payload do LID 0x01 (69 bytes, com eco) para um cenário.

    Usado pelo comando `field-test`. Levanta ValueError para cenário
    desconhecido ou payload com tamanho errado.
    """
    key = scenario.lower()
    if key not in ANALYZERS:
        raise ValueError(f"cenário desconhecido: {scenario}; válidos: {', '.join(ANALYZERS)}")
    if len(payload) != 69:
        raise ValueError(f"LID 0x01 do TCM deve ter 69 bytes (com eco); recebido {len(payload)}")
    if label:
        print(f"  Rótulo: {label}")
    print(HYPOTHESIS_WARNING)
    parsed = parse_lid01(payload)
    ANALYZERS[key](parsed)
    print("\n  — Payload bruto —")
    print("  " + payload.hex(" "))
    print(SEPARATOR)
    return parsed


def capture_and_analyze(scenario: str, dll_path: str, label: str | None = None):
    """Captura o LID 0x01 do TCM ao vivo e analisa.

    A captura usa `scanner.snapshot_lids` só no LID 0x01 (sessão KWP
    descoberta, mesmo caminho dos snapshots de 2026-10-23), então o JSON
    fica salvo em logs/ como qualquer snapshot.
    """
    from openscan_obd.scanner import snapshot_lids

    path = snapshot_lids(dll_path, "tcm_cvt", label or f"field_{scenario}", 0x01, 0x01)
    lids = json.loads(path.read_text(encoding="utf-8")).get("lids", {})
    raw_hex = lids.get("0x01")
    if not raw_hex:
        raise RuntimeError(f"TCM não devolveu o LID 0x01; snapshot salvo em {path}")
    return run_analysis(scenario, bytes.fromhex(raw_hex), label)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(USAGE)
        sys.exit(0)

    label = sys.argv[1].lower()

    if label not in ANALYZERS:
        print(f"Label desconhecido: {label}")
        print(f"Labels válidos: {', '.join(ANALYZERS)}")
        sys.exit(1)

    # Payload: 2º argumento ou referência
    if len(sys.argv) >= 3:
        hex_str = " ".join(sys.argv[2:])
    else:
        hex_str = REFERENCE_PAYLOAD_HEX
        print(f"[INFO] Usando payload de referência (marcha_lenta). Passe o hex real como 2º argumento.")

    payload = bytes(int(x, 16) for x in hex_str.split())
    parsed = parse_lid01(payload)
    ANALYZERS[label](parsed)

    print()
    print("  — Payload bruto —")
    raw = [int(x, 16) for x in hex_str.split()]
    for i in range(0, len(raw), 9):
        chunk = raw[i:i+9]
        hex_part  = " ".join(f"{v:02X}" for v in chunk)
        idx_part  = " ".join(f"[{i+j:2d}]" for j in range(len(chunk)))
        print(f"  {idx_part}")
        print(f"  {hex_part}")
    print(SEPARATOR)


if __name__ == "__main__":
    main()
