"""
Catálogo de DIDs (Data Identifiers) e endereços de ECU conhecidos.

Status da pesquisa (atualizado 2026-10-23):
- Os DIDs genéricos de UDS (ISO 14229-1 Annex F) são padronizados e estão
  preenchidos abaixo com confiança.
- NÃO existe hoje um catálogo público confiável dos DIDs específicos do
  CVT Nissan do Sentra B16 2010 2.0 (JF011E/RE0F10A). O app CVTz50 é comercial/fechado (não é
  open-source, ao contrário do que eu supus antes), e os projetos abertos
  que encontrei (OpenConsult, nissanecu wiki) cobrem protocolos/ECUs
  diferentes (Consult I pré-OBD-II, ECU de motor) — nenhum documenta o
  TCM/CVT.
- O caminho real pra popular CVT_DIDS é sniffing do tráfego CAN do próprio
  veículo, ou leitura ativa via UDS assim que soubermos o endereço do
  TCU/CVT. Documente a fonte de cada entrada confirmada.
"""

# Genéricos (ISO 14229-1 Annex F) — padronizados, uso seguro, não exigem
# SecurityAccess (0x27) pra leitura. Qualquer ECU compatível com UDS
# costuma responder pelo menos a um subconjunto destes.
GENERIC_DIDS = {
    0xF190: "VIN (Vehicle Identification Number)",
    0xF18C: "ECU Serial Number",
    0xF1A2: "Software Version",
    0xF1A0: "Boot Software Identification",
    0xF187: "Spare Part Number",
    0xF189: "ECU Software Version Number",
    0xF18A: "System Supplier Identifier",
    0xF18B: "ECU Manufacturing Date",
    0xF191: "Vehicle Manufacturer ECU Hardware Number",
    0xF192: "System Supplier ECU Hardware Number",
    0xF193: "System Supplier ECU Hardware Version Number",
    0xF194: "System Supplier ECU Software Number",
    0xF195: "System Supplier ECU Software Version Number",
    0xF197: "System Name or Engine Type",
    0xF198: "Repair Shop Code or Tester Serial Number",
    0xF19E: "ASAM-MCD-2D ECU-Identifier",
}

# Endereçamento padrão SAE J2012 / ISO 15031-5 pra até 8 ECUs no barramento
# OBD-II (11-bit, ISO 15765-4). Isso é documentação pública de norma, não
# é específico da Nissan nem é engenharia reversa de nada proprietário —
# é o esquema que qualquer veículo OBD-II compatível (2008+) costuma
# seguir nas requisições funcionais. Útil pra achar o endereço do TCU sem
# precisar sniffar primeiro: basta tentar UDS básico (TesterPresent /
# DiagnosticSessionControl) em cada par abaixo e ver quem responde.
#
# request -> (response, descrição usual)
STANDARD_ADDRESSES: dict[int, tuple[int, str]] = {
    0x7E0: (0x7E8, "ECU de motor (PCM/ECM) — já confirmado no nosso carro"),
    0x7E1: (0x7E9, "TCU/TCM (transmissão) — candidato principal pro CVT"),
    0x7E2: (0x7EA, "Sistema híbrido (não aplicável — Sentra não é híbrido)"),
    0x7E3: (0x7EB, "Reservado / específico do fabricante"),
    0x7E4: (0x7EC, "Reservado / específico do fabricante"),
    0x7E5: (0x7ED, "Reservado / específico do fabricante"),
    0x7E6: (0x7EE, "Reservado / específico do fabricante"),
    0x7E7: (0x7EF, "Reservado / específico do fabricante"),
}

# CVT Sentra B16 2010 2.0 (JF011E / RE0F10A) — VAZIO DE PROPÓSITO.
# Preencher somente após confirmar via sniffing do CAN do próprio veículo,
# ou leitura ativa UDS no endereço do TCU (ver STANDARD_ADDRESSES acima e
# docs/protocol_notes.md). Formato sugerido:
#   0x1234: "descrição (fonte: sniff 2026-xx-xx / leitura ativa em 0x7E1)"
CVT_DIDS: dict[int, str] = {}


# Tier B — tabela de módulos candidatos do Nissan.
# Headers de 11 bits derivados do Nissan Leaf (mesma era) — padrão Nissan
# resposta = request + 0x20. NÃO confirmados pro Sentra B16 2010: validar
# no carro (ver docs/protocol_notes.md, MAPA TIER B v0). Modelo orientado a
# dados (lição do ddt4all): mexer aqui, não no código.
#   protocol: "obd2" (SAE J1979 padrão) ou "kwp" (KWP2000 serviço 0x21).

NISSAN_MODULES: dict[str, dict] = {
    # CONFIRMADOS presentes no CAN (discover 23/10/2026 e can_id_scan
    # 24/10/2026: responderam a 0x10 0x81 e/ou 0x10 0xC0). "Confirmado" aqui
    # quer dizer que o par tx/rx responde; nao confirma identidade nem dados.
    "engine":  {"tx": 0x7E0, "rx": 0x7E8, "protocol": "obd2", "note": "Motor/ECM - CONFIRMADO (tambem aceita KWP 10 C0; LID 0x01 = 4 bytes)"},
    "tcm_cvt": {"tx": 0x7E1, "rx": 0x7E9, "protocol": "kwp",  "note": "CVT/TCM - CONFIRMADO (0x21 responde sob sessao 0xC0; sob 0x81 -> NRC 0x80)"},
    "eps":     {"tx": 0x742, "rx": 0x762, "protocol": "kwp",  "note": "Direcao EPS - CONFIRMADO (discover)"},
    "meter":   {"tx": 0x743, "rx": 0x763, "protocol": "kwp",  "note": "Painel/Combination Meter - CONFIRMADO (discover)"},
    "bcm":     {"tx": 0x745, "rx": 0x765, "protocol": "kwp",  "note": "BCM - CONFIRMADO (discover)"},
    "ipdm":    {"tx": 0x74D, "rx": 0x76D, "protocol": "kwp",  "note": "IPDM - CONFIRMADO (discover)"},
    # Responde em tx+0x10 (nao +0x20). Identidade desconhecida; ABS/VDC e
    # hipotese nao verificada. Encontrado por can_id_scan 24/10/2026.
    "unk_71e": {"tx": 0x71E, "rx": 0x72E, "protocol": "kwp",  "note": "Modulo 0x71E - responde 10 C0; identidade NAO confirmada (ABS/VDC?)"},
    # NAO responderam ao toque de sessao nos pares abaixo (offsets +0x20,
    # varreduras 0x700-0x7FF). Motivo desconhecido: outro ID, K-line ou
    # sessao diferente. Mantidos anotados; o scan vai mostra-los como ausente.
    "abs_vdc": {"tx": 0x740, "rx": 0x760, "protocol": "kwp",  "note": "ABS/VDC - NAO respondeu neste par (ver unk_71e)"},
    "airbag":  {"tx": 0x752, "rx": 0x772, "protocol": "kwp",  "note": "SRS/Airbag - NAO respondeu neste par"},
    "hvac":    {"tx": 0x744, "rx": 0x764, "protocol": "kwp",  "note": "HVAC - NAO respondeu neste par"},
}
