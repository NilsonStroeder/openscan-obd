# Roteiro de Sessão no Carro — Sentra B16 2010

**Script:** `car_session.py` (na raiz do projeto)  
**Data planejada:** 2026-10-25+  
**Veículo:** Nissan Sentra B16 2010 / câmbio JF011E / RE0F10A  
**Hardware:** GODIAG GD101, porta COM9  

---

## TL;DR — Sequência mínima recomendada

```cmd
cd <pasta-do-projeto>
.venv\Scripts\activate
python car_session.py all
```

Roda tudo em ordem: enumeração → ECM KWP → TCM snapshot → BCM/IPDM/EPS/METER → polling correlacionado.  
Logs ficam em `logs/` — copie tudo de volta para análise offline.

---

## Antes de ir ao carro (fazer agora, no computador)

### 1. Verificar ambiente
```cmd
cd <pasta-do-projeto>
.venv\Scripts\activate
python -c "from openscan_obd.kwp import build_start_session; print('OK')"
```

### 2. Fechar TODO app que usa a porta COM antes de ir ao carro
- Consult-III Plus → fechar
- J1979 Diagnostic Tool → fechar
- Qualquer outro diagnóstico

---

## Nota sobre endereços CAN (pesquisa 2026-10-24)

Pesquisa confirmou: **não existe lista pública e definitiva de endereços 0x7xx para B16/C11**.

| Módulo | TX | RX | Status |
|--------|----|-----|--------|
| ECM | 0x7E0 | 0x7E8 | ✅ Padrão OBD-II — confirmado |
| TCM CVT | 0x7E1 | 0x7E9 | ✅ Confirmado no nosso carro |
| ABS/VDC | 0x740 | 0x760 | ⚠️ Não respondeu antes — alternativa: 0x7E2/0x7EA (padrão SAE) |
| EPS | 0x742 | 0x762 | 🟡 Respondeu ao discover; nunca lido |
| METER | 0x743 | 0x763 | 🟡 Respondeu ao discover; nunca lido |
| BCM | 0x745 | 0x765 | 🟡 Respondeu ao discover; nunca lido |
| IPDM | 0x74D | 0x76D | 🟡 Respondeu ao discover; nunca lido |
| HVAC | 0x744 | 0x764 | ⚠️ Não respondeu antes |
| SRS/Airbag | 0x752 | 0x772 | ⚠️ Não respondeu antes |

Fontes pesquisadas: nisprog (fenugrec), opendbc (comma.ai), ISO 15765-4.  
Resultado: ECM/TCM confirmados; periféricos (BCM/IPDM/METER) foram descobertos por bus sweep no nosso carro em 23/10/2026 — são os valores reais.

---

## No carro — Preparação

1. Chave na posição **II** (ignição, painel aceso)
2. Conectar GD101 na porta OBD-II (sob o volante)
3. GD101 no notebook via USB
4. Confirmar COM9 no Gerenciador de Dispositivos
5. Terminal na pasta do projeto com venv ativo

---

## Sequência completa de comandos

### Passo 0 — Teste rápido de conexão
```cmd
python examples_read_vin.py
```
Se der VIN ou "presente" → hardware ok. Seguir.

---

### Passo 1 — Enumeração de módulos
```cmd
python car_session.py enum
```
Pinga todos os módulos, mostra quem responde.  
**Duração:** ~1 min

---

### Passo 2 — ECM via KWP (PRIORIDADE MÁXIMA)
```cmd
python car_session.py ecm
```
- Tenta `10 C0`, `10 87`, `10 85`... em 0x7E0/0x7E8
- Se abrir sessão → varre **todos os LIDs 0x00–0xFF**
- Log em `logs/ecm_TIMESTAMP.json`

**Por que é crítico:** ECM em KWP pode ter TPS, APP, MAF, RPM, AFR, ignition timing  
— tudo que está não mapeado e não aparece no TCM LID 0x01.

---

### Passo 3 — TCM snapshot completo
```cmd
python car_session.py tcm
```
- Captura todos os 33 LIDs catalogados
- Sweep dos LIDs desconhecidos (0x04–0x0F, 0x22–0x3F, etc.)
- Log em `logs/tcm_snapshot_TIMESTAMP.json`

**Fazer com carro parado, motor ligado, seletor em P**

---

### Passo 4 — Módulos confirmados que nunca foram lidos
```cmd
python car_session.py bcm
python car_session.py ipdm
python car_session.py eps
python car_session.py meter
```

| Módulo | Pode conter |
|--------|-------------|
| BCM (0x745) | Brake switch, lights, door sensors, tensão bateria |
| IPDM (0x74D) | Relés, cooling fan, fuel pump status |
| EPS (0x742) | Torque de direção, sensor de ângulo |
| METER (0x743) | ODO, speedometer — pode ter VSP independente |

---

### Passo 5 — Módulos que não responderam antes
```cmd
python car_session.py abs
python car_session.py airbag
python car_session.py hvac
```

ABS: o script tenta 0x740/0x760 primeiro; se não responder, tentar manualmente:
```cmd
python -m openscan_obd.cli probe-kwp --only abs_vdc
```
E se ABS estiver em 0x7E2/0x7EA (alternativa SAE):
```cmd
python -m openscan_obd.cli scan-dids --dll "C:\...\GODIAG_PT32.dll" --txid 7E2 --rxid 7EA --start 00 --end FF
```

---

### Passo 6 — Field tests guiados (LID 0x01 TCM)
```cmd
python car_session.py field
```

O script instrui cada estado no terminal. Estados a capturar:

| Label | Estado | Objetivo |
|-------|--------|---------|
| `P_frio` | Ligar frio, P idle | ATF TEMP lookup — b[9] < 47 |
| `P_quente` | P idle quente | Baseline ATF ~60°C |
| `N_idle` | N idle | Range SW em N |
| `D_idle` | D, pé no freio | Range SW D, STM inicial |
| `R_parado` | R, pé no freio | **Confirmar b[40]=0x5A permanente** |
| `D_rpm1000/2000/3000` | D, frenado, RPM fixo | ENG_SPEED vs PRI, b[5] |
| `D_arranque` | Arrancada suave D | SLIP, STM em movimento |
| `cruising_60/80/100` | Cruzeiro constante | VSP b[3,4] — fórmula exata |
| `tcc_100` | 100 km/h, throttle mínimo | **b[42]=0, b[38]=ON** |
| `accel_P_leve/pleno` | P, acelerando no lugar | **APP — encontrar em b[48-67]** |
| `decel_100_0` | Engine braking | STM e b[42] em decel |

---

### Passo 7 — Polling correlacionado TCM + OBD
```cmd
python car_session.py correlated --duration 300
```

5 minutos de polling simultâneo: LID 0x01 TCM + RPM/VSP/TPS/ECT via OBD.

**O CSV vai resolver:**
- b[3,4] vs OBD VSP → fórmula exata de km/h
- b[6,7] vs OBD RPM → confirmar ENG SPEED
- b[42] vs velocidade → entender escala de SLIP

---

## Ou rode tudo de uma vez

```cmd
python car_session.py all
```

---

## Prioridades se o tempo for curto

Se tiver só **30 minutos**:
1. `python car_session.py ecm` — ECM KWP (nunca feito, maior impacto)
2. `python car_session.py field` — só: R_parado, tcc_100, accel_P_pleno
3. `python car_session.py correlated --duration 120`

Se tiver **1 hora+**: `python car_session.py all`

---

## Troubleshooting

| Problema | Causa | Fix |
|----------|-------|-----|
| `PermissionError: Acesso negado (COM9)` | Outro app usando a porta | Fechar Consult-III, J1979 Tool |
| `Nenhuma sessão aceita` no ECM KWP | ECM pode precisar de carro ligado | Tentar com motor rodando |
| `Nenhuma sessão aceita` no BCM/IPDM | Endereço RX errado (0x765 vs 0x74D) | Anotar NRC; o discover de 23/10 é a fonte |
| Dados zeros no LID 0x01 | Sessão expirada | Script envia keepalive; se persistir, reiniciar |
| COM9 não aparece | GD101 não reconhecido | Reconectar USB; verificar driver GODIAG |

---

## Regras invariáveis

- ❌ Nunca 0x27 SecurityAccess
- ❌ Nunca 0x2E/0x31 (escrita/rotinas)
- ❌ Nunca inventar fórmulas sem fonte ou medição cruzada
- ✅ Só ler, só documentar o que foi medido
