# CVT TCM — Decodificação do LID 0x01 (KWP2000 0x21)

**Módulo:** TCM/CVT — Nissan Sentra B16 2010, câmbio JF011E / RE0F10A (CVT8 JATCO)
**Protocolo:** KWP2000 (ISO 14230) sobre CAN, serviço 0x21
**Sessão necessária:** 0x10 0xC0 (subtipo 0xC0 — sem isso, 0x21 retorna NRC 0x80)
**Endereço CAN:** TX=0x7E1 / RX=0x7E9
**Tamanho do payload:** 69 bytes (byte[0] = echo do LID = 0x01, ignorar na decodificação)

---

## Snapshots de referência

| Label | Timestamp | RPM (engine) | Temp coolant | Estado |
|-------|-----------|-------------|--------------|--------|
| `marcha_lenta` | 2026-10-23T16:41:29 | ~700 rpm | 84°C | Motor quente, P, idle |
| `acelerado`    | 2026-10-23T16:41:52 | ~3000 rpm | 83°C | Motor quente, P, acelerado |

Payload hex completo:

```
marcha_lenta:
01 00 00 01 00 01 16 3A 00 7C B2 00 08 02 02 16 7F EB 00 00 00 00 00 01 01 01 03
7E 25 00 83 24 C8 2D 2D D8 42 26 FE FE FE 02 78 02 A0 02 6D 02 76 02 A0 02 6D 00
11 00 00 00 01 00 0A 11 12 03 00 06 00 00 5F

acelerado:
01 00 00 01 00 01 5D 46 00 7B B1 00 08 02 02 5D 7F EB 00 17 17 17 18 02 01 02 04
84 33 00 83 26 C8 2D 2D D8 6D 32 82 82 FE 02 78 02 2E 02 50 02 79 02 2E 02 50 00
10 00 00 00 01 00 0A 11 12 03 00 07 00 00 5F
```

---

## Mapa de bytes — estado atual

Indexação: byte[0] = echo LID, byte[1]..byte[68] = dados reais.

| Byte(s) | idle (hex/dec) | accel (hex/dec) | Δ | Hipótese | Fórmula | Confiança | Como confirmar |
|---------|---------------|----------------|---|----------|---------|-----------|----------------|
| [0] | 01 | 01 | 0 | Echo do LID | — | ✅ Fixo | — |
| [6] | 0x16 / 22 | 0x5D / 93 | +71 | RPM eixo primário CVT (byte alto) | — | 🟡 Alta | Snapshots a 1k/2k/3k RPM fixos |
| [6,7] WORD BE | 0x163A / 5690 | 0x5D46 / 23878 | +18188 | **ENG SPEED (rpm motor)** — não é PRI SPEED | WORD_BE ÷ 8 → idle=711, accel=2984 RPM | ✅ Confirmado 2026-11-05 (correlação OBD 0x0C, r=0.967, n=331) | — |
| [9] | 0x7C / 124 | 0x7B / 123 | -1 | Temperatura (ATF?) — **invertida**: [30] = 255−[9] | Lookup da tabela abaixo aplicado a [9] dá resultado invertido (frio=203 → ~138 °C). Hipótese: aplicar a [30] | 🔴 Revisar (2026-11-05) | Partida a frio com ECT OBD simultâneo |
| [10] | 0xB2 / 178 | 0xB1 / 177 | -1 | **Engine Coolant Temp (via CAN do ECM)** — ESM RE0F10A documenta apenas 1 sensor físico de temp no corpo de válvulas (byte[9]). byte[10] candidato = temperatura do líquido de arrefecimento recebida via CAN. | Lookup table? (mesmo range que byte[9]?) — a extrapolação ≈ 100°C+ não pode ser confirmada sem tabela para este byte | 🔴 Hipótese | Carro frio — verificar se byte[10] cai antes de byte[9] (fluido aquece mais devagar que coolant) |
| [15] | 0x16 / 22 | 0x5D / 93 | +71 | RPM eixo secundário CVT (espelho [6]) | Mesmo padrão byte[6] | 🟡 Alta | RPM fixos — se divergir de [6] durante cruising, é secundário real |
| [19] | 0x00 / 0 | 0x17 / 23 | +23 | APP Sensor 1 ou TPS Sensor 1? | valor = % | 🔴 Hipótese (valores consistentes, sem fonte documental) | Acelerador leve/médio/fundo |
| [20] | 0x00 / 0 | 0x17 / 23 | +23 | Sensor redundante [19] | valor = % | 🔴 Hipótese | Idem |
| [21] | 0x00 / 0 | 0x17 / 23 | +23 | Sensor redundante [19] | valor = % | 🔴 Hipótese | Idem |
| [22] | 0x00 / 0 | 0x18 / 24 | +24 | Sensor redundante [19] (valor ligeiramente diferente) | valor = % | 🔴 Hipótese | Idem |
| [23] | 0x01 / 1 | 0x02 / 2 | +1 | CTP Switch (Closed Throttle Position / Idle Switch) | 1=ON (idle), 2=OFF (acelerador pressionado) | 🔴 Hipótese forte | Snapshots P/N/D sem acelerar |
| [25] | 0x01 / 1 | 0x02 / 2 | +1 | **Flag de estado independente** — +1 em [25] e +1 em [26] simultaneamente. Se fosse WORD_BE, o salto seria +257 (0x0103→0x0204). O incremento separado de +1 cada confirma que são **dois bytes independentes**, não um WORD. Candidatos: Idle Switch / CTP Switch (Gemini: flags de interruptor). | — | 🔴 Hipótese (arquitetura de flags confirmada — significado não confirmado) | Snapshots com pedal em 0% / 5% / 50% — observar qual byte muda primeiro |
| [26] | 0x03 / 3 | 0x04 / 4 | +1 | **Flag de estado independente** (ver [25]) | — | 🔴 Hipótese | Idem |
| [36,37] WORD BE | 0x4226 / 16934 | 0x6D32 / 27954 | +11020 | **Posição do Step Motor** (Ratio Control Motor) — ESM RE0F10A: "The step motor's 4 aspects of ON/OFF change according to signal from TCM. The flow of line pressure to primary pulley is changed and pulley ratio is controlled." ATSG: range físico 0–177 steps. ⚠️ Valores brutos (16934/27954) não mapeiam diretamente para steps — divisor desconhecido. Se WORD ÷ 96 = idle≈176 (quase LOW ratio em P), seria plausível. | WORD_BE ÷ ? = posição 0–177 steps. Tentativa: ÷96 → idle=176 ≈ posição LOW (P) | 🔴 Hipótese forte (variável documentada no ESM — associação e escala não confirmadas) | Cruising a velocidade constante — ratio deve mudar para HIGH (step próximo de 0); comparar com ratio calculado |
| [38] | 0xFE / 254 | 0x82 / 130 | -124 | **0xFE = marcador "inativo/não calculado"** no protocolo KWP Nissan (confirmado — RomRaider, ddt4all: 0xFE e 0xFF indicam dado não calculado ou estado inativo). Em idle = inativo. Ao acelerar, TCM ativa cálculo → valor 130. Candidatos: duty cycle de solenóide ou slip do conversor. | Quando ativo: valor = ÷ ? (escala não confirmada) | 🔴 Hipótese (0xFE=inativo **confirmado** por 2 fontes; significado de 0x82=130 não confirmado) | Arranque suave em D — se mudar ao engatar → relacionado ao conversor/TCC |
| [39] | 0xFE / 254 | 0x82 / 130 | -124 | **Idem [38]** — mesmo comportamento 0xFE→0x82. Dois bytes independentes com mesmo marcador de inativo (não um WORD — salto seria 0xFEFE→0x8282 = -31,868, visto como valor WORD BE). | — | 🔴 Hipótese | Idem — verificar se [38] e [39] divergem em algum estado |
| [44,45] WORD LE | 0xA0,0x02 / 672 | 0x2E,0x02 / 558 | -114 | **Pressão de linha CVT** | WORD_LE ÷ 1000 = MPa → idle=0.672 MPa, accel=0.558 MPa ✓ faixa spec (0.5–1.5 MPa idle) | 🔴 Hipótese forte | Parado vs acelerando vs neutro |
| [46,47] WORD LE | 0x6D,0x02 / 621 | 0x50,0x02 / 592 | -29 | **Pressão secundária?** — ESM RE0F10A documenta Secondary Pressure Sensor (códigos P0840/P0841/P0868) como grandeza monitorada e controlada pelo TCM (target + real). Candidato plausível para este offset. | WORD_LE ÷ 1000 = MPa → idle=0.621, accel=0.592 | 🔴 Hipótese (variável existe no sistema — associação a este offset não confirmada) | Teste P/N/D — pressão secundária deve subir em D |
| [48,49] WORD LE | 0x76,0x02 / 630 | 0x79,0x02 / 633 | +3 | **Pressão target ou sensor redundante?** — bloco [44-51] potencialmente contém múltiplas pressões (line/secondary, target/actual). Valor quase estável sugere target (comando) vs actual (leitura real). | — | 🔴 Hipótese | Testar stall (pressão max) — target deve ser constante, actual deve subir |
| [50,51] WORD LE | 0xA0,0x02 / 672 | 0x2E,0x02 / 558 | -114 | **Redundante de [44,45]** ou pressão target de linha? — valores idênticos a [44,45] em ambos os snapshots. Pode ser target vs actual com valores iguais em steady-state, ou simples espelho/checksum. | — | 🔴 Hipótese | Acelerar bruscamente — [44,45] e [50,51] devem divergir momentaneamente se target ≠ actual |
| [54] | 0x11 / 17 | 0x10 / 16 | -1 | Nibble alto = seletor? (0x1_=P, 0x4_=N, 0x8_=D, 0x2_=R) | — | 🔴 Hipótese (2026-11-05, bate em todas as capturas exceto accel25_D/accel50_D=0x49) | Capturas N e R em movimento |
| [65] | 0x06 / 6 | 0x07 / 7 | +1 | Contador de evento / DTC count / gear? | — | 🔴 Hipótese | — |
| [68] | 0x5F / 95 | 0x5F / 95 | 0 | Checksum ou marcador de fim | — | 🟡 Provável | Fixo em todos os snapshots |

### Bytes estáveis (não mudaram nos 2 contrastes)
`[1-5]`, `[8]`, `[11-14]`, `[16-18]`, `[29-30]`, `[32-35]`, `[40-43]`, `[53]`, `[55-64]`, `[66-68]`

---

## ATF TEMP COUNT — Tabela de conversão (não-linear)

Fonte: Nissan Electronic Service Manual, seção CVT — Diagnóstico de temperatura do ATF.
Aplicável ao TCM JF011E / RE0F10A (verificado para Murano CVT, mesmo câmbio mecânico).

> ⚠️ **A fórmula `valor - 40 = °C` está INCORRETA.** A tabela abaixo é a referência correta.

| COUNT (byte[9]) | Temperatura ATF |
|-----------------|----------------|
| 4 | -30°C |
| 47 | 20°C |
| 83 | 40°C |
| **124** | **60°C** |
| 169 | 85°C |
| 243 | 200°C |

Para valores intermediários, interpolar linearmente entre os pontos mais próximos.

**Exemplo do snapshot idle:** byte[9] = 124 → **60°C** de fluido CVT.
Com coolant a 84°C no mesmo instante, a diferença de ~24°C é perfeitamente realista — o fluido CVT aquece mais devagar que o refrigerante do motor.

---

## Grandezas mecânicas JF011E — Confirmadas

Fonte: Manual técnico JATCO para JF011E / RE0F10A (atoc.ru — tradução russa do manual oficial JATCO).

| Grandeza | Valor | Referência |
|---------|-------|-----------|
| Ratio mínimo (LOW) | **2.349:1** | Manual JATCO JF011E |
| Ratio máximo (HIGH/OD) | **0.394:1** | Manual JATCO JF011E |
| Ratio marcha ré | **1.750:1** (fixo) | Manual JATCO JF011E |
| Pressão de linha idle | **0.5–1.5 MPa** (5–15 bar) | Manual JATCO JF011E |
| Pressão de linha stall | até **6.0 MPa** (60 bar) | Manual JATCO JF011E |
| Posição Step Motor | **0–177 steps** (range documentado em diagnóstico) | Gemini/ddt4all — não verificado primariamente |

---

## Legenda de confiança

| Símbolo | Significado |
|---------|-------------|
| ✅ Confirmado | 2+ contrastes independentes com evidência cruzada |
| 🟡 Alta | 1 contraste + evidência cruzada de outra fonte, ou fundamentado em arquitetura documentada |
| 🔴 Hipótese | Variação observada, significado não confirmado |

> **Regra do projeto:** `CVT_DIDS` em `dids.py` só recebe uma entrada após status ✅.

---

## Próximos testes planejados

### Prioridade 1 — Carro frio (manhã, antes de ligar)
```bash
python -m openscan_obd snapshot tcm_cvt --label frio
```
**Objetivo:** confirmar byte[9] = ATF TEMP COUNT via tabela.
**Esperado:** byte[9] < 0x30 (< 47 → < 20°C se frio). Se valor for < 47, confirma tabela lookup.

### Prioridade 2 — RPM fixos (1000 / 2000 / 3000) com taquímetro
```bash
python -m openscan_obd snapshot tcm_cvt --label rpm_1000
python -m openscan_obd snapshot tcm_cvt --label rpm_2000
python -m openscan_obd snapshot tcm_cvt --label rpm_3000
```
**Objetivo:** confirmar `WORD_BE(byte[6],byte[7]) ÷ 8 = RPM` e verificar se byte[15] diverge em cruising (secundário real).

### Prioridade 3 — Posição do câmbio (P / N / D sem acelerar)
```bash
python -m openscan_obd snapshot tcm_cvt --label posicao_P
python -m openscan_obd snapshot tcm_cvt --label posicao_N
python -m openscan_obd snapshot tcm_cvt --label posicao_D_idle
```
**Objetivo:** decodificar byte[23]. Se permanecer 1 em N e D sem acelerar → é CTP switch (não seletor de marcha). Se mudar → é seletor.

### Prioridade 4 — Acelerador em posições fixas (20% / 50% / 100%)
**Objetivo:** confirmar bytes[19-22] como APP/TPS em %. Usar scanners que reportem % de abertura para correlação.

### Prioridade 5 — Cruising estável (60 km/h constante em D)
**Objetivo:** decodificar bytes[36,37] como posição do step motor. Ao cruzar, o motor de passo deve estar em posição diferente de idle (que fica em posição mais alta/redução maior). Verificar se WORD÷? = valor entre 0 e 177.

### Prioridade 6 — Pressão de linha (comparar P / D / N)
**Objetivo:** confirmar bytes[44,45] WORD LE ÷ 1000 = MPa. Em D idle a pressão deve subir vs P idle.

---

## Referências consultadas

- Logs capturados: `logs/snapshot_tcm_cvt_marcha_lenta_20261023_164122.json`
- Logs capturados: `logs/snapshot_tcm_cvt_acelerado_20261023_164145.json`
- Log de sonda: `logs/kwp_probe_20261023_163645.txt` (33 LIDs confirmados)
- Protocolo: `docs/protocol_notes.md` (pesquisa KWP2000, sessão 0xC0, qashqai)
- Manual JATCO JF011E (via atoc.ru): ratio 2.349–0.394, pressão 0.5–1.5 MPa idle, Step Motor 0–177 steps
- Nissan ESM CVT (Murano, academia.edu): tabela ATF TEMP COUNT não-linear (COUNT 124 → 60°C)
- Arquitetura Nissan APP/TPS: ESMs Nissan — quadruplicação de sensores no barramento CAN
- ddt4all (Renault/Nissan alliance): cobertura parcial; arquivos X61_CVT/FK0 citados mas não inspecionados diretamente
- Gemini AI research (1ª rodada): avaliado e cruzado — correto em ratio, pressão e RPM; ATF TEMP formula estava incorreta; step motor position plausível
- Copilot AI research (2ª rodada, 2026-10-23): ESM RE0F10A component list — CVT fluid temp sensor, line pressure solenoid, **secondary pressure sensor**, secondary pressure solenoid, step motor, TCC solenoid; PRI SPEED variável do Data Monitor Consult-III (diagnóstico P1778); Step Motor ESM description (4 aspects ON/OFF, primary pulley flow control)
- Gemini AI research (2ª rodada, 2026-10-23): **0xFE confirmado como marcador "inativo/não calculado"** no protocolo KWP Nissan (RomRaider, ddt4all); bytes[25,26] = dois flags independentes (não WORD); byte[10] candidato Engine Coolant Temp via CAN (ESM: apenas 1 sensor físico no RE0F10A); Secondary Pressure documentada (P0840/P0841/P0868); Step Motor range 0–177 (ATSG)
- **Próximo alvo de pesquisa (Copilot):** tabela completa Data Monitor Consult-III para RE0F10A — se listar PRI SPEED, SEC SPEED, SECONDARY PRESSURE, LINE PRESSURE, STEP MOTOR → permite casar quantidade de grandezas com posições do payload

---

## Status da pesquisa externa

Pesquisa executada em 2026-10-23. Conclusões:

1. **Não existe documentação pública** do byte map LID 0x01 para TCM JF011E. ✓ (Gemini correto)
2. **ddt4all** tem cobertura parcial Renault/Nissan — útil mas não específica para este TCM. ✓
3. **Ratio e pressão** confirmados de fonte primária (manual JATCO). ✓ Gemini correto.
4. **bytes[19-22] como APP/TPS** é hipótese bem fundamentada na arquitetura, sem fonte direta do byte map. 🟡
5. **byte[23] como CTP switch** é hipótese plausível, sem fonte direta. 🔴
6. **RPM = WORD_BE ÷ 8** é aritmeticamente correto e consistente — referência ddt4all citada pelo Gemini não verificada diretamente. 🟡
7. **ATF TEMP COUNT**: fórmula `valor - 40` está **incorreta**. Lookup table oficial mostra COUNT 124 → 60°C (não 84°C). Fluido CVT a 60°C com coolant a 84°C é realista. ⚠️ Correção crítica.
8. **0xFE = marcador de inativo** no protocolo KWP Nissan: confirmado por Gemini citando RomRaider e ddt4all. Válido para bytes[38,39] em idle. Esta é a confirmação mais sólida da 2ª rodada de pesquisa.
9. **bytes[25,26] = flags independentes** (não WORD): confirmado por análise de Gemini — incremento +1 cada, simultâneo, seria +257 como WORD. Arquitetura de dois flags separados confirmada.
10. **ESM RE0F10A documenta apenas 1 sensor de temperatura físico** no corpo de válvulas. byte[10] como Engine Coolant Temp via CAN permanece hipótese mas é o único candidato restante.
11. **PRI SPEED confirmada** como variável do Data Monitor Consult-III (Copilot, diagnóstico P1778). Suporta bytes[6,7] como RPM primário.
12. **Próximo alvo:** tabela completa Data Monitor Consult-III RE0F10A — Copilot e Gemini concordam que este é o caminho mais promissor para mapear grandezas → offsets.

---

## Achados da análise offline — 13 payloads (2026-10-23)

13 payloads de field tests analisados: frio, neutro, D/aceleração, cruising 60 km/h, cruising 80 km/h, R, ESM P0744 e outros.
Commit de referência: `82b82a9`.

### b[31] — Espelho exato de b[6] (PRI SPEED byte alto)

⚠️ **Refutado em 2026-11-05:** `b[31] == b[6]` falha em 391 de 403 payloads; [31] fica perto de 0x23–0x24. O byte que espelha [6] é [15] (358/403). Texto original mantido abaixo como histórico.

Em todos os 13 cenários testados, `b[31] == b[6]` sem exceção.

- b[6] = byte alto do WORD_BE de PRI SPEED
- b[31] = cópia exata — redundância de canal CAN (common em barramento Nissan)
- Não é uma grandeza independente — desconsiderar para decodificação de novos parâmetros

### bytes[19-22] — VEHICLE SPEED ❌ (substituído por [3,4] ✅ em 2026-11-05; mantido como histórico)

**Hipótese anterior:** ACC PEDAL POS (%) → **REFUTADA**
- Em idle parado: b[19]=0x00, como esperado para pedal solto
- Mas em cruising a 60 km/h: b[19]=0x1D (29), b[20]=0x1E (30) → 0% de pedal em cruising? Impossível.

**Nova hipótese:** VEHICLE SPEED × 2 = km/h

| Cenário | b[19] | b[20] | b[21] | b[22] | ×2 (b[19]) | Vel. esperada |
|---------|--------|--------|--------|--------|------------|---------------|
| parado/idle | 0x00 | 0x00 | 0x00 | 0x00 | 0 km/h | 0 ✅ |
| cruising60  | 0x1D | 0x1E | 0x1D | 0x1E | 58 km/h | ~60 km/h ✅ |
| cruising80  | 0x27 | 0x27 | 0x27 | 0x29 | 78 km/h | ~80 km/h ✅ |

- Dois pares redundantes: [19,20] e [21,22] — mesma grandeza duplicada
- Fórmula: `VSP km/h = b[19] × 2` (ou b[20], b[21] — consistentes)
- **Milhas descartado:** 29 mph = 46 km/h, não bate com "cruising60". Carro Mercosul/Brasil → km/h.
- Confirmar com GPS verificado em próximo field test

### b[27,28] — Flags de regime operacional 🟡

Três estados discretos identificados:

| Estado do veículo | b[27] (hex) | b[28] (hex) | Descrição |
|------------------|-------------|-------------|-----------|
| P / N / frio (motor frio) | 0x7E | 0x25 | Neutro / sem carga |
| D / R em aceleração | 0x84 | 0x33 | Marcha engatada, carga |
| Cruising estável | 0x40 | 0x0E | Regime de cruzeiro |

- Não mapeados em documentação pública — hipótese: estado do solenóide TCC ou modo de controle da CVT
- Teste pendente: seletor em R → bate com D (0x84/0x33) ou com P/N (0x7E/0x25)?

### b[32-35] — Anomalia de cruising 🔴

Em todos os cenários parados: `b[32]=0xC8, b[33]=0x2D, b[34]=0x2D, b[35]=0xD8` — completamente estáticos.

Em cruising 60 km/h e 80 km/h: valores mudam drasticamente, com b[33] == b[34] sempre idênticos.

| Cenário | b[32] | b[33] | b[34] | b[35] |
|---------|--------|--------|--------|--------|
| parado (todos) | 0xC8 | 0x2D | 0x2D | 0xD8 |
| cruising60 | — | cresceu | cresceu | — |
| cruising80 | — | maior ainda | maior ainda | — |

- b[33] == b[34] em todos os cenários analisados → redundância ou WORD_BE onde ambos mudam juntos
- Hipótese: corrente de solenóide OD / duty cycle do lock-up em regime de cruzeiro
- Offset nunca analisado antes desta sessão

### b[38] — LOCK UP flag 🟡 (confirmado como candidato forte)

- 0xFE em 12 dos 13 cenários (todos parados + acelerados) → TCC não aplicado
- ESM P0744 (TCC Solenoid Valve fault): no payload capturado com o carro com DTC P0744 ativo, b[38] permaneceu 0xFE → consistente (TCC travado OFF pelo DTC)
- Teste pendente: cruising a ~100 km/h, 30+ segundos, aceleração leve → verificar se b[38] muda para valor ≠ 0xFE

### b[39] — ❌ DESCARTADO como SLIP REV

- Comportamento **invertido** em relação ao esperado para slip do conversor
- Em cruising estável (lock-up esperado → slip próximo de zero): b[39] apresentou valor **maior** que em idle
- Grandeza real em b[39] desconhecida — offset real de SLIP REV não identificado nos 69 bytes analisados

---

## Mapa de parâmetros — diagnóstico Sentra B16 CVT (estado 2026-10-23)

Cruzamento entre parâmetros desejáveis para scanner e status atual no LID 0x01 TCM.

| Parâmetro | Bytes LID 0x01 | Status | Observação |
|-----------|----------------|--------|------------|
| ENG SPEED (rpm) | [6,7] WORD_BE ÷ 8 | ✅ Confirmado | Correlação OBD 2026-11-05. PRI SPEED: offset desconhecido |
| CVT Fluid Temp | [9] / [30] lookup | 🔴 Revisar | [9] cai quando aquece; [30]=255−[9]. Ver auditoria 2026-11-05 |
| Range Switch (P/N/D/R) | [54] nibble alto? | 🔴 Hipótese | [23-25] descartado: R=(2,2,2), P desligado=(21,1,21) |
| STM STEP | [36,37] WORD_BE ÷ ? | 🔴 Hipótese | ÷96 chega a 439 (> 177 físico) em 195/331 amostras |
| Vehicle Speed | [3], [4] = km/h 1:1 | ✅ Confirmado | Correlação OBD 0x0D 2026-11-05. [19-22] descartado como VSP; [11,12] espelho 🟡 |
| SEC SPEED (rpm) | [15] | 🟡 Candidato | Escala pendente — diverge de [6] em cruising? |
| Engine Coolant Temp | [10] | 🟡 Candidato | Lookup igual a b[9]? |
| Espelho de [6] | [15] | 🟡 Espelho | [15]=[6] em 358/403; [31] NÃO espelha [6] |
| Regime flags | [27,28] | 🟡 Candidato | 3 estados: neutro / carga / cruzeiro |
| LOCK-UP Status | [38] | 🟡 Candidato | 0xFE=OFF confirmado em 12/13 |
| LINE PRESSURE | [44,45] WORD_LE | 🟡 Candidato | Fórmula ÷1000 MPa pendente |
| Cruising solenoid? | [32-35] | 🔴 Hipótese | Muda drasticamente só em cruising |
| SEC PRESSURE | [46,47] WORD_LE | 🔴 Hipótese | Pouca variação nos testes disponíveis |
| GEAR RATIO | calculado | 🔴 Derivado | = PRI ÷ SEC quando SEC confirmado |
| **SLIP REV** | **?** | **⬜ TODO** | b[39] descartado — offset real desconhecido |
| APP / borboleta | [19-22]? | 🔴 Hipótese | r=0.89 com OBD TPS (confundido com RPM). Ver auditoria 2026-11-05 |
| **Brake Switch** | **?** | **⬜ TODO** | Flag binário — candidato em [26] ou [40-43] |
| ENG RPM motor | [6,7] WORD_BE ÷ 8 | ✅ Confirmado | Ver acima |
| TPS, MAF, AFR, STFT, LTFT, IAT, Timing | fora do TCM | ❌ Fora de escopo | ECM — endereço 0x7E0→0x7E8, LID diferente |
| Wheel Speeds ABS | fora do TCM | ❌ Fora de escopo | Módulo ABS — outro endereço CAN |

### Bytes ainda não analisados (40 bytes — TODO)
`[1-5]`, `[8]`, `[11-14]`, `[16-18]`, `[26]`, `[29-30]`, `[40-43]`, `[48-67]`

Faixa [40-67] é a mais promissora para encontrar APP, SLIP REV e Brake Switch.

---

## Arquitetura multi-módulo — nota para o scanner

O TCM (0x7E1→0x7E9) expõe apenas grandezas internas da CVT e dados recebidos via CAN de outros módulos.
Para um scanner de diagnóstico completo, são necessários pelo menos dois LIDs de dois módulos distintos:

| O que monitorar | Módulo | CAN TX→RX |
|----------------|--------|-----------|
| RPM motor, TPS, MAF, AFR, STFT, LTFT, Timing, IAT | ECM | 0x7E0→0x7E8 |
| PRI/SEC SPEED, STM STEP, pressões, ATF temp, LOCK-UP | TCM | 0x7E1→0x7E9 |
| Wheel Speeds, ABS | ABS | outro endereço |

O mapeamento dos LIDs do ECM é trabalho futuro e independente deste projeto.

---

## Próximos field tests — prioridade revisada (pós análise offline)

| Prioridade | Teste | Objetivo |
|-----------|-------|----------|
| 1 | Cruising com GPS verificado | Confirmar bytes[19-22] ×2 = km/h |
| 2 | TCC a ~100 km/h, 30s, aceleração leve | Confirmar b[38] muda (LOCK-UP ON) |
| 3 | Aceleração em P (não D) | Isolar APP sem regime flags de D — encontrar offset pedal |
| 4 | Seletor R estático | Verificar b[27,28]: igual a D (0x84/0x33) ou P/N (0x7E/0x25)? |
| 5 | ~~Carro frio antes de ligar~~ | Feito 2026-10-24: b[9]=203 (não < 47) — lookup refutado para [9]. Repetir com ECT OBD para escalar [30] |

---

## Correlação LID 0x01 × OBD-II (2026-11-05, offline)

Fonte: `logs/correlated_20261024_165235_20261024_165235.csv`, 331 amostras,
300 s, 0–52 km/h, OBD via `physical_7E0`. Pearson:

| Bytes | PID OBD | r | Diferença média | Resultado |
|-------|---------|---|-----------------|-----------|
| [6,7] WORD_BE ÷ 8 | RPM 0x0C | 0.967 | −9 rpm (624–2819) | ✅ ENG SPEED |
| [3] | VSP 0x0D | 0.993 | +0.09 km/h | ✅ km/h 1:1 |
| [4] | VSP 0x0D | 0.993 | −0.03 km/h | ✅ km/h 1:1 |
| [11] / [12] | VSP 0x0D | 0.992 / 0.984 | +0.05 / +0.69 km/h | 🟡 espelho |
| [42] | TPS / VSP | 0.30 / 0.48 | — | não é TPS |

Lock-up [38] ficou OFF em 331/331 (máx. 52 km/h). A temperatura ATF por
lookup de [9] deu ~26 °C com ECT OBD 83–89 °C — revisar o lookup.

---

## Auditoria dos logs (2026-11-05, offline)

403 payloads do LID 0x01 (capturas correlacionadas, snapshots, snapshot a
frio, field tests, reverse_state, kwp_probe e fixtures). Todos com 69 bytes,
[0]=0x01, [68]=0x5F; [1], [2], [8], [29] = 0x00 em 403/403; [40]=0x5A só nas
duas capturas em R; o hex dos snapshots bate com as fixtures.

**Rebaixados (✅ → 🔴):**
- **[9] ATF:** cai quando o carro aquece (203 frio → 52–58 quente;
  r([9], tempo) = −0.94). [30] = 255−[9] (±1) em todos os payloads menos 1 (`correlated_20261024_095936` registro 17: [9]=76, [30]=177, diferença 2). Hipótese não
  verificada: o lookup vale para [30] (~23 °C frio, ~64 °C idle quente; o
  valor quente da tarde, ~130 °C, cai numa faixa esparsa da tabela e é
  suspeito).
- **[23-25] Range:** R = (2,2,2); P motor desligado = (21,1,21)/(23,1,23);
  em movimento 0–20 e 250–255 (int8 com sinal?).
- **[36,37]÷96 STM:** 88–439, 195/331 amostras acima do físico 177.

**Outras correções:** [31] não espelha [6] (391/403 falham; quem espelha é
[15]). [40] fora de R não é sempre 0xFE (58 3E/3F em 17–20 km/h). [12] = 8
sempre que [4] = 0 — não é espelho limpo. [27,28] e [30], [32-35] mudam entre
capturas paradas.

**Hipóteses novas (🔴, não verificadas):**
- [19-22] ~ borboleta/pedal: r=0.89 com OBD TPS, mas r=0.88 com RPM.
- [18] int8 com sinal ~ aceleração do veículo (r=0.94 com dVSP/dt).
- [54] nibble alto ~ seletor (P/N/D/R = 0x1/0x4/0x8/0x2).
- Nenhum byte de [48-67] acompanha TPS (|r| ≤ 0.33, exceto [54]).

**Código:** `car_session.py` (`decode_lid01_live`) rotula `LOCKUP_b38` como
ON sempre que [38] ≠ 0xFE e expõe `GEAR_b41`/`SLIP_b42`/`VSP_b12` como se
fossem confirmados; os campos `decoded` dos logs herdam isso. A fixture
`lid01_field_20261023.json` (14 capturas) não tem arquivo de origem em
`logs/`.

