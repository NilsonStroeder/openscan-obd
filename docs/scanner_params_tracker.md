# Scanner Diagnóstico — Rastreamento de Parâmetros

**Última atualização:** 2026-11-05 (auditoria dos logs)  
**Veículo de referência:** Nissan Sentra B16 2010, câmbio JF011E / RE0F10A

> **Legenda de status:**  
> ✅ Confirmado — 2+ contrastes independentes com evidência cruzada  
> 🟡 Candidato forte — hipótese sólida, precisa de mais 1 field test ou correlação  
> 🔴 Hipótese fraca — variação observada, significado não confirmado  
> ❌ Descartado — hipótese refutada  
> ⬜ TODO — não identificado ainda  
>
> **Coluna "Onde procurar":**  
> Indica qual módulo/LID é o candidato mais provável. Não significa que está confirmado lá — significa onde buscar primeiro. Tudo na lista é escopo do scanner.

---

## GRUPO: Motor / Carga

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| TPS (Throttle Position %) | ⬜ TODO | ECM LID (0x7E0) — nunca tentado KWP | ? | ? | ECM nunca foi varrido com `10 C0`. Alta probabilidade de estar num LID do ECM |
| APP / Accelerator Pedal Position % | ⬜ TODO | TCM LID 0x01 [40-67]? ou ECM LID | ? | ? | TCM recebe do ECM via CAN. Deve estar exposto em algum LID — não identificado. Field test: aceleração em P |
| MAF (g/s) | ⬜ TODO | OBD-II PID 0x10 (ECM 0x7E0) | SAE J1979 | ? | ECM declara o PID no bitmap de 2026-11-15; falta a leitura ao vivo no carro (dashboard v2 já pede) |
| MAP (kPa) | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| Calculated Load % | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| Engine Load % | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |

---

## GRUPO: Rotação

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| RPM motor (crankshaft) | ⬜ TODO | ECM LID (0x7E0) | ? | ? | OBD-II PID 0x0C lê RPM. ECM aceitou `10 C0` em 2026-10-24, mas LID 0x01 do ECM tem só 5 bytes (`01001b0000`); outros LIDs não varridos. No TCM, ver ENG SPEED abaixo |
| ENG SPEED (rpm motor, via CAN) | ✅ Confirmado | TCM LID 0x01 | [6,7] WORD_BE | ÷ 8 = rpm | idle=711, accel=2984 nos field tests. Correlação com OBD PID 0x0C: captura `logs/correlated_20261024_165235` (n=331, 0–52 km/h), r=0.967, diferença média −9 rpm (faixa 624–2819 rpm) — 2º contraste após os 14 field tests. Promovido em 2026-11-05. É rotação do motor, não PRI SPEED (polia) |
| PRI SPEED (rpm polia primária CVT) | 🔴 Offset desconhecido | TCM LID 0x01 | ? | ? | Ver revisão 2026-10-23 — offset original [6,7] reclassificado como ENG SPEED |
| PRI SPEED mirror | ❌ Descartado como independente | TCM LID 0x01 | [31] | = b[6] em cruzeiro | Espelha b[6] APENAS nas capturas de cruzeiro (3/14). Nos demais ≈36 constante |
| SEC SPEED (rpm polia secundária CVT) | 🔴 Hipótese | TCM LID 0x01 | [42]? ou [15]? | ? | b[15] espelha b[6]. b[42] cresce com velocidade (87 a 60km/h, 201 a 80km/h) — candidato novo. Cai para 0 no teste TCC (lock-up?) |
| Idle Target RPM | ⬜ TODO | ECM LID (0x7E0) | ? | ? | ECM KWP nunca tentado |

---

## GRUPO: Mistura

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| AFR / Air-Fuel Ratio | ⬜ TODO | ECM LID (0x7E0) | ? | ? | ECM KWP nunca tentado |
| Lambda | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| STFT (Short Term Fuel Trim) | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| LTFT (Long Term Fuel Trim) | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| Injector Pulse Width (ms) | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Sem PID padrão. LID 0x01 do ECM tem 4 bytes; só 0x01 e 0x83 responderam em 2026-10-24. Falta varredura 0x00-0xFF (roteiro próximo, `ecm_sweep_full`) |

---

## GRUPO: Ignição

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| Ignition Timing / Spark Advance | ⬜ TODO | ECM LID (0x7E0) | ? | ? | ECM KWP nunca tentado |
| Knock Retard | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| Knock Sensor Activity | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |

---

## GRUPO: Ar e Combustível

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| Fuel Rail Pressure | ⬜ TODO | ECM LID (0x7E0) | ? | ? | ECM KWP nunca tentado |
| Duty Cycle bomba de combustível | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| Injector Duty Cycle | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |

---

## GRUPO: Temperaturas

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| ECT (Engine Coolant Temp) | 🟡 Candidato | TCM LID 0x01 via CAN do ECM | [10] | lookup (mesma de b[9]?) | ESM: apenas 1 sensor físico de temp no RE0F10A (ATF). b[10] é o único candidato. Carro frio → verificar se cai antes de b[9] |
| IAT (Intake Air Temp) | ⬜ TODO | OBD-II PID 0x0F (ECM 0x7E0) | SAE J1979 | ? | ECM declara o PID no bitmap de 2026-11-15; falta a leitura ao vivo no carro (dashboard v2 já pede) |
| CVT Fluid Temp (ATF) | 🟠 Estimado (2026-11-15) | TCM LID 0x01 | [9] (e [30] = 255−[9]) | lookup não-linear — byte/direção em dúvida | ❌ Lookup aplicado a [9] dá resultado invertido: frio antes de ligar [9]=203 (~138 °C pelo lookup), quente à tarde 52–58; r([9], tempo)=−0.94 em `correlated_20261024_165235`. [30] = 255−[9] (±1) em todos os payloads menos 1 (`correlated_20261024_095936` registro 17: [9]=76, [30]=177, diferença 2). Hipótese não verificada: a tabela vale para [30] (~23 °C frio, ~64 °C idle quente). Confirmar com partida a frio + ECT OBD | **Decisão 2026-11-15:** o dashboard usa [30] pela tabela do ESM com selo 'estimado' até haver referência independente.
| Catalytic Converter Temp | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Raro — depende do modelo. ECM KWP nunca tentado |

---

## GRUPO: Velocidade

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| Vehicle Speed (km/h) | ✅ Confirmado | TCM LID 0x01 | [3] e [4] | b[3] = b[4] = km/h (1:1) | Field tests: 56/57 a 60 km/h, 77/77 a 80 km/h. Correlação com OBD PID 0x0D: captura `logs/correlated_20261024_165235` (n=331, 0–52 km/h), r=0.993 (b[3]) / 0.993 (b[4]), diferença média +0.09 / −0.03 km/h — 2º contraste após os 14 field tests. Promovido em 2026-11-05. Validado até 52 km/h na correlação e 80 km/h nos field tests. [19-22] não é VSP (zera no TCC) |
| Vehicle Speed — espelho | 🟡 Candidato | TCM LID 0x01 | [11,12] | ≈ km/h | r=0.992 (b[11]) / 0.984 (b[12]); b[12] fica em média +0.69 km/h acima. Redundante com [3,4]; significado exato de b[12] não confirmado |
| Wheel Speeds (ABS) | ⬜ TODO | Módulo ABS | ? | ? | ABS (0x740) não respondeu ao session request. Pode ser K-Line ou ID diferente |

---

## GRUPO: CVT (RE0F10A / JF011E) — foco principal

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| PRI SPEED (rpm) | 🔴 Offset desconhecido | TCM LID 0x01 | ? | ? | [6,7] é ENG SPEED (ver grupo Rotação), não PRI SPEED |
| SEC SPEED (rpm) | 🟡 Candidato | TCM LID 0x01 | [15] | ÷ ? pendente | Escala não calculada. Diverge de [6] em cruising |
| GEAR RATIO | 🔴 Derivado | Calculado | — | PRI ÷ SEC | Calculável quando SEC confirmado |
| STEP MOTOR POSITION | 🔴 Hipótese (rebaixado 2026-11-05) | TCM LID 0x01 | [36,37] WORD_BE | ÷ 96 = steps? | Físico: 0–177 steps (ESM). ÷96 dá 88–439 em `correlated_20261024_165235`, 195/331 amostras acima de 177 — escala ou atribuição errada. Varia com o regime, por isso continua candidato |
| LINE PRESSURE (MPa) | 🟡 Candidato | TCM LID 0x01 | [44,45] WORD_LE | ÷ 1000 = MPa | idle=0.672, accel=0.558. Dentro spec (0.5–1.5 MPa) |
| SECONDARY PRESSURE (MPa) | 🔴 Hipótese | TCM LID 0x01 | [46,47] WORD_LE | ÷ 1000 = MPa | ESM documenta sensor (P0840/P0841). Pouca variação nos testes |
| LOCK-UP STATUS | 🟡 Candidato | TCM LID 0x01 | [38] | 0xFE=OFF | OFF em 12/13 cenários incl. DTC P0744. Confirmar ON a ~100 km/h |
| SLIP REV (rpm) | ❌ b[39] descartado / ⬜ offset desconhecido | TCM LID 0x01 [40-67]? | ? | ? | b[39] descartado: comportamento INVERTIDO. b[42] novo candidato (ver análise 2026-10-24) |
| REVERSE FLAG | ✅ Confirmado | TCM LID 0x01 | [40] | 0x5A=Ré | 0x5A só nas duas capturas em R (403 payloads). Fora de R costuma ser 0xFE, mas `correlated_20261024_165235` registros 57, 58, 182, 183 têm [39,40]=58 3E/3F (17–20 km/h) — não usar 0xFE como "não-ré" |
| GEAR ENGAGED FLAG | 🟡 Alta | TCM LID 0x01 | [41] | 0=P/N, 1=D/R/cruzeiro, 2=P+rpm | Padrão limpo em 14 cenários |
| RANGE SW (P/R/N/D) | ✅ Confirmado (2026-11-15) | TCM LID 0x01 | [54] nibble alto | 0x1_=P, 0x4_=N, 0x8_=D, 0x2_=R | 112/112 payloads das 8 leituras de seletor (P,N,D,R,R,D,N,P) de 2026-11-15, rótulo do roteiro vs nibble. [23-25] continua descartado. Exceção antiga: fixtures accel25_D/accel50_D (0x49) são de 2026-10 e ficam como anomalia aberta. Veículo: Sentra B16 2010 apenas.
| CVT TEMP (ATF) | 🔴 Revisar (2026-11-05) | TCM LID 0x01 | [9] / [30] | lookup não-linear | Idem CVT Fluid Temp |
| Regime flags | 🟡 Candidato | TCM LID 0x01 | [27,28] | 3 estados | 0x7E/0x25=neutro, 0x84/0x33=carga, 0x40/0x0E=cruzeiro |
| Cruising solenoid? | 🔴 Hipótese | TCM LID 0x01 | [32-35] | ? | Estático parado, muda dramaticamente só em cruising |

---

## GRUPO: Sondas

| Parâmetro | Status | Onde procurar | Bytes conhecidos | Fórmula | Observação |
|-----------|--------|---------------|------------------|---------|------------|
| A/F Sensor Voltage / Lambda | ⬜ TODO | ECM LID (0x7E0) | ? | ? | ECM KWP nunca tentado |
| O2 Sensor B1S1 | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |
| O2 Sensor B1S2 | ⬜ TODO | ECM LID (0x7E0) | ? | ? | Idem |

---

## Bytes mapeados vs não-analisados no LID 0x01 TCM

**Análise offline 2026-10-24 — 14 cenários verificados:**

```
[0]     — echo LID = 0x01 (ignorar)
[1,2,8,29] — ESTÁTICOS = 0x00 em todos os 14 cenários → descartar
[3,4]   — VEHICLE SPEED km/h 1:1 ✅ (correlação OBD 2026-11-05)
[5]     — varia com regime (1 parado, 11 arranque, 43 cru60, 48 cru80) — indicador de gear?
[6,7]   — ENG SPEED WORD_BE ÷ 8 ✅ (correlação OBD 2026-11-05)
[9]     — temperatura invertida (= 255−[30]); lookup ATF em revisão 🔴
[10]    — ECT via CAN (espelha b[9]+offset) 🟡
[11,12] — espelha [3,4] — 4 bytes redundantes VSP 🟡
[13]    — ESTÁTICO
[14,15] — espelha b[6] em todos os cenários — descartado como SEC independente
[16-18] — ESTÁTICOS
[18]    — int8 com sinal ~ aceleração do veículo (r=0.94 com dVSP/dt, ~1.22 km/h/s por contagem) 🔴 não verificado
[19-22] — borboleta/pedal? r=0.89 com OBD TPS (confundido com RPM, r=0.88); [19]=0 ↔ TPS ~14% (fechada) 🔴 não verificado
[23-25] — NÃO é RANGE SW (R=(2,2,2)); variável com sinal? 🔴
[26]    — diverge de b[25] em aceleração/TCC 🔴
[27,28] — regime flags (3 estados) 🟡
[29]    — ESTÁTICO
[30]    — = 255−[9] (±1) em todos os payloads menos 1 (`correlated_20261024_095936` registro 17: [9]=76, [30]=177, diferença 2) — mesma temperatura, invertida 🟡
[31]    — espelha b[6] só em cruzeiro — descartado como independente ❌
[32-35] — solenóide candidato (muda em cruzeiro) 🔴
[36,37] — STM STEP? ÷96 passa de 177 — escala errada 🔴
[38]    — LOCK-UP flag candidato (0xFE=OFF) 🟡
[39]    — DESCARTADO como SLIP REV ❌
[40]    — REVERSE FLAG ✅ (0x5A só em R; fora de R geralmente 0xFE, às vezes 0x3E/0x3F)
[41]    — GEAR ENGAGED (0=P/N, 1=D/arranque, 2=P+rpm) 🟡
[42]    — SLIP/SEC_SPEED candidato (87 a 60km/h, 201 a 80km/h, 0 no TCC) 🔴
[43]    — varia em accel/arranque — sem interpretação 🔴
[44,45] — LINE PRS S/V WORD_LE 🟡
[46,47] — SEC PRES WORD_LE 🔴
[48-67] — não analisados — CANDIDATOS para parâmetros desconhecidos ⬜
[68]    — marcador de fim = 0x5F 🟡
```

---

## Resumo executivo

| Grupo | ✅ | 🟡 | 🔴 | ⬜ TODO | ❌ |
|-------|----|----|-----|---------|----|
| Motor / Carga | 0 | 0 | 0 | 6 | 0 |
| Rotação | 1 | 0 | 2 | 2 | 1 |
| Mistura | 0 | 0 | 0 | 5 | 0 |
| Ignição | 0 | 0 | 0 | 3 | 0 |
| Ar e Combustível | 0 | 0 | 0 | 3 | 0 |
| Temperaturas | 0 | 1 | 1 | 2 | 0 |
| Velocidade | 1 | 1 | 0 | 1 | 0 |
| CVT | 1 | 5 | 7 | 1 | 0 |
| Sondas | 0 | 0 | 0 | 3 | 0 |
| **TOTAL** | **3** | **7** | **10** | **26** | **1** |

> **Nota sobre contagens 2026-10-24:** PRI SPEED [6,7] foi reclassificado de ✅ para 🟡 (ENG SPEED candidato).
> REVERSE FLAG [40] e GEAR ENGAGED [41] foram adicionados como novos ✅ e 🟡 respectivamente.
>
> **2026-11-05:** ENG SPEED [6,7] e Vehicle Speed [3,4] promovidos a ✅ pela correlação com OBD (`logs/correlated_20261024_165235`). [11,12] separado como espelho 🟡. Linha PRI SPEED do grupo CVT corrigida para 🔴 (estava ✅ desatualizada).
>
> **2026-11-05 (auditoria dos logs, 403 payloads LID 0x01):** ATF [9], RANGE SW [23-25] e STM [36,37]÷96 rebaixados de ✅ para 🔴 — contrariados pelos logs (ver linhas de cada um). Contagens acima recalculadas automaticamente a partir das tabelas de cada grupo (linhas repetidas entre grupos contam em cada grupo).

**Observação:** O ECM aceitou `10 C0` em 2026-10-24, mas o LID 0x01 dele tem só 4 bytes de dados; LIDs fora de 0x01–0x09/0x20/0x83 nunca foram varridos. Os ⬜ de motor dependem dessa varredura ou de PIDs OBD-II padrão.

---

## Próximos field tests — por impacto

| Prioridade | Ação | Requer carro? | Parâmetros desbloqueados |
|-----------|------|---------------|--------------------------|
| 1 | Probe KWP no ECM (0x7E0) | ❌ Não | TPS, RPM, APP, MAF, AFR, STFT, LTFT, Timing, sondas |
| 2 | ~~Captura LID 0x01 + OBD simultâneos~~ | — | Feito: VSP e RPM ✅ (2026-11-05). TPS/ECT ainda não correlacionados com [48-67]/[10] |
| 3 | Ler LIDs 0x80, 0x83, 0x12–0x21 do TCM | ❌ Não (logs existentes) | Identificação módulo, parâmetros extras |
| 4 | Probe KWP no BCM (0x745) e IPDM (0x74D) | ❌ Não | Brake Switch, tensões |
| 5 | Cruising > 80 km/h com OBD VSP | ✅ Sim | Estender a validação de [3,4] para velocidades altas |
| 6 | TCC a ~100 km/h, 30s | ✅ Sim | LOCK-UP ON → ✅ |
| 7 | Aceleração em P | ✅ Sim | APP offset em [40-67] |
| 8 | Seletor R estático | ✅ Sim | Regime flags b[27,28] em R |
