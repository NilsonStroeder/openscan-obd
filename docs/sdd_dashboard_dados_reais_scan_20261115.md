# SDD — Dashboard com dados reais do veículo + scan de falhas e dados do CVT

**Status (2026-11-15):** F0–F4 implementadas e testadas offline (336 testes + 10 de navegador
em Chrome real); branch `claude/dashboard-real-data`. **Nada do caminho `--hardware` novo foi
validado no carro.** Decisões da seção 8 registradas lá.

| Fase | Estado | Pendente no carro |
|---|---|---|
| F0 higiene | ✅ feito | — |
| F1 OBD no ECM, frame v2 | ✅ feito (mock) | RPM/ECT/TPS/tensão em marcha lenta batem com o scan de hoje |
| F2 TCM no mesmo poller | ✅ feito (mock); latências em `frame.timing` (`cycle_ms`, `obd_ms`, `tcm_ms`, `tcm_obd_skew_ms`) | `set_ids` no hardware; ciclo ≤ 500 ms; defasagem ≤ 100 ms |
| F3 guarda RF7, scan, abas Falhas/Scan | ✅ feito | scan completo no carro |
| F4 `probe-dtc` (H1–H3; H5 com `--allow-a3 --confirm-parked`) | ✅ comando pronto | rodar H1–H3, depois H5 (carro parado em P, freio de mão) |
| F5 etapa 13 em movimento | ⏳ só no carro | VSP > 0, ré, lock-up |

**Veículo de teste:** Nissan Sentra B16 2010, CVT JF011E/RE0F10A, GODIAG GD101 (J2534).
Nada vale para outro veículo sem evidência própria (ver `AGENTS.md`).
**Base:** logs de 2026-11-15 em `logs/` + estado do repositório após a queda do notebook.

---

## 0. Resumo

1. O dashboard ficou vazio porque lê só o LID 0x01 do ECM por KWP. No B16 esse
   LID tem 4 bytes constantes (`001b0000`) e o decoder exigia 13 ou mais. Os
   2.737 frames do teste deram `decode_error`. A conexão estava boa; o dado era
   inútil. O ECM entrega o que o dashboard precisa por OBD-II modo 01.
2. O agente que travou deixou o trabalho pela metade: criou as funções certas
   (`read_obd_live`, `read_obd_dtcs`, `set_ids`) mas não ligou nenhuma ao
   poller, à API nem à tela.
3. Proposta: dashboard com fonte por grandeza (OBD no ECM, LID 0x01 no TCM),
   estado honesto por card, um scan sob demanda somente leitura e uma aba de
   falhas que nunca afirma "sem falhas" onde a leitura não foi validada.

---

## 1. Diagnóstico

### 1.1 Onde o agente parou

Reconstruído pelos arquivos (a transcrição dele não está na pasta). Última
edição por volta de 21:36; o notebook travou depois disso.

| Item | Estado |
|---|---|
| `gateway/j2534.py` | `set_ids(tx, rx)` + `PassThruStopMsgFilter`. Troca o filtro de fluxo sem fechar o canal. **Nunca rodou no carro.** |
| `gateway/j2534_mock.py` | Fixture do TCM, respostas de modo 01 gravadas hoje, modos 03/07, `set_ids`. |
| `gateway/poller.py` | `read_obd_live()` e `read_obd_dtcs()` criados. **`KWPPoller` não chama nenhuma.** |
| `gateway/tcm_lid01.py` e `tests/fixtures/tcm_lid01_raw.hex` | Novos, não rastreados. |
| `api/main.py`, `static/dashboard.html` | **Intocados** (últimas mudanças em 5-6/nov). |
| Testes novos | **Nenhum.** Os 251 existentes passam (`pytest tests`, sem browser). |
| `docs/session_log_20261115.md` | Citado no docstring de `tcm_lid01.py`, **não existe**. |
| `docs/scanner_params_tracker.md` | Não atualizado hoje (ATF, marcha e ré seguem 🔴 lá). |

Ruído de fim de linha: os três arquivos modificados estão em CRLF e o
repositório em LF. `git diff` mostra 716/52/396 linhas, mas as mudanças reais
são 34/52/66. Normalizar antes de commitar.

### 1.2 Por que o dashboard ficou vazio

Evidência: `logs/gateway_ecm_20261115_183945.jsonl` (5 min, 2.737 frames,
8,8 Hz) e o screenshot um screenshot do dashboard (removido do repositório).

- `conn=true`, `lid_response=positive`, `raw_lid01="001b0000"` em 100% dos frames.
- `decode_error: "ECM LID 0x01: esperado >= 13 bytes, recebido 4"` em 100%.
- O front só preenche os cards quando `data.conn && data.lid_available` **e**
  o campo existe. Sem campo, todos mostram "—", e o topo continua dizendo
  "KWP conectado". A tela afirma que está tudo bem enquanto não mostra nada.
- O mesmo ECM responde por OBD modo 01 (`full_scan_20261115_184513.txt`): ECT
  94 °C, RPM 710, VSP 0, TPS 12,5 %, módulo 14,3 V.

### 1.3 O que a suíte de hoje cobriu

| Etapa | Resultado |
|---|---|
| 1-3 adaptador, TCM frio, aquecimento 15 min | OK (985 amostras TCM+OBD) |
| 4 dashboard | 5 min, parado por tempo; **vazio (causa em 1.2)** |
| 5-6 scan OBD, DTC KWP | OK; **`18` deu NRC 0x11 no ECM e no TCM** (2 formatos cada) |
| 7-9 ECM, módulos, 0x71E/BCM/IPDM/EPS/painel | rodaram, **sem arquivo correspondente em `logs/`** (saída só no console) |
| 10-11 seletor P/N/D/R, ré | OK (9 snapshots + 30 amostras) |
| 12 acelerar em P | **interrompida**: pedia 120 s, gravou ~70 s (74 amostras) |
| 13 rodando 20 min | **não rodou** |

Consequência: **nenhum dado com carro em movimento hoje.** VSP, lock-up e
qualquer coisa que dependa de velocidade continuam sem novo contraste.

---

## 2. Achados dos dados de hoje e ajustes propostos

| # | Achado | Evidência | Ajuste |
|---|---|---|---|
| A1 | ECM LID 0x01 é constante e inútil para o live | 2.737/2.737 frames `001b0000` | Parar de usar como fonte de dados; manter só como bruto de diagnóstico |
| A2 | ECM expõe live por OBD: PIDs 04 05 06 07 0C 0D 0E 0F 10 11 13 14 15 1C 1F 21 2E 30 31 42 43 44 45 46 47 4C | bitmaps em `full_scan_20261115_184513.txt` | Fonte do dashboard "Geral" (tabela 5.1) |
| A3 | Sem PID de MAP (0x0B) nem de pulso de injeção | bitmap não os lista | Remover cards de "pulso de injeção" e "hipótese" que não têm fonte; mostrar "indisponível neste veículo" |
| A4 | VIN falha por design: `09 02` não é suportado (modo 09 só tem 04 e 06) | bitmap `09 00 = 04, 06` | Tratar como "não suportado", não como erro. Ler Cal ID (`09 04`) e CVN (`09 06`) |
| A5 | Conexão alternada TCM↔ECM custa ~0,36 s por ciclo (ciclo 0,91 s, ~1 Hz) | `t_RPM − t_tcm` p50 = 0,36-0,37 s; `correlated_poll` abre e fecha o canal a cada módulo | Trocar IDs sem reconectar (`set_ids` ou dois filtros ativos). Meta: ciclo ≤ 500 ms |
| A6 | Cada PID OBD leva ~20 ms | `t_VSP−t_RPM`, `t_TPS−t_VSP`, `t_ECT−t_TPS` p50 = 0,02 s | 8 PIDs ≈ 160 ms. Cabe em ≥ 2 Hz com o TCM junto |
| A7 | O alerta "REGRESSÃO" do RPM em `analisar_logs.py` foi artefato de tempo | RPM na aceleração: r=0,895 bruto → **0,965** com OBD interpolado no instante do TCM; inclinação 0,98; partida a frio r=0,998, inclinação 1,002 | O analisador deve compensar a defasagem antes de acusar regressão. A diferença de −37 rpm em transiente só fecha com amostragem > 4 Hz |
| A8 | O alerta de VSP é falso por falta de variação | OBD VSP = 0 em 1.059/1.059 amostras: r é indefinido | Analisador: "indeterminado (sem variação)" em vez de "REGRESSÃO" |
| A9 | Em repouso `[3]=1` e `[4]=0` | 985/985 amostras | Usar `[4]` como conferência do VSP; `[3]` tem +1 em 0 km/h. Confirmar em movimento (etapa 13) |
| A10 | ATF por `[30]` e tabela ESM: 72→103 (~35→49 °C) com ECT 32→84 °C | `analise_20261115_190321.md` §5 | Exibir como **estimado**, com selo. A única referência é a tabela ESM; não há sensor independente |
| A11 | Seletor pelo nibble alto de `[54]`: 112/112 (P=1 N=4 D=8 R=2). Nibble baixo muda (0/1 em marcha, 9 nos snapshots) e não é explicado | análise §6 | Mostrar marcha; guardar `[54]` cru. O "rótulo" do seletor vem do que o operador declarou, não de sensor |
| A12 | Lock-up `[38]` só visto parado (0xFE/0x81/0x82) | análise §7 | Continua 🔴. Fica como byte cru até a etapa 13 |
| A13 | DTC por KWP `0x18` não existe no ECM nem no TCM | NRC 0x11 nos 4 testes | Retirar `18` do caminho do dashboard; ver seção 5.5 |
| A14 | OBD modos 03/07 no ECM: `4300` / `4700` (nenhum DTC) | `full_scan_20261115_184513.txt` | Fonte de DTC válida **para o ECM** |
| A15 | Arquivos de hoje sem log: etapas 7-9 | `logs/` | O roteiro deve redirecionar a saída de `car_session.py` para arquivo |

---

## 3. Objetivos e fora de escopo

**Objetivos**
- O1. Mostrar no dashboard, ao vivo, os valores reais do veículo, cada um com
  sua origem e seu grau de confiança.
- O2. Quando algo não puder ser lido, dizer isso na tela, em vez de "—".
- O3. Scan sob demanda: módulos presentes, identificação, DTCs onde a leitura
  é validada, snapshot decodificado do CVT.
- O4. Fechar a lacuna de hoje: capturar com o dashboard ligado, em movimento.

**Fora de escopo:** escrita (`2E`), rotinas (`31`), limpeza de DTC (`04`, `14`),
SecurityAccess (`27`), reflash, descompilar o Consult-III, celular/ELM327 (já
tem SDD próprio) e qualquer promessa de compatibilidade com outros carros.

**Regras que continuam valendo** (ver AGENTS.md): só leitura; nada de
valor de LID sem 2+ contrastes independentes; pesquisar antes de codificar.

---

## 4. Requisitos

| ID | Requisito |
|---|---|
| RF1 | O poller lê PIDs OBD do ECM e o LID 0x01 do TCM no mesmo ciclo, sem fechar o canal entre módulos |
| RF2 | Cada valor traz `source`, `tier`, `age_ms` e `raw` |
| RF3 | Card sem dado mostra o motivo (`sem resposta`, `NRC 0x..`, `não suportado`), nunca só "—" |
| RF4 | O cabeçalho só diz "dados ao vivo" se houver valores recentes; senão "conectado, sem dados" |
| RF5 | Valor com `age_ms` acima do limite aparece como obsoleto |
| RF6 | Scan sob demanda gera `logs/scan_<ts>.json` e a aba Scan o exibe |
| RF7 | Um guarda central recusa qualquer serviço fora da lista de leitura (5.4) |
| RF8 | A aba Falhas separa "nenhum DTC" de "leitura não validada neste módulo" |
| RF9 | Chaves planas atuais (`rpm`, `vsp`, `ect`, `tps`) continuam no frame, por compatibilidade |
| RNF1 | Metas a medir (não validadas): RPM/VSP/TPS ≥ 5 Hz; TCM ≥ 2 Hz; lentos ~1 Hz; defasagem TCM↔OBD ≤ 100 ms |
| RNF2 | Testes offline sem carro; fixtures vindas dos logs de hoje |
| RNF3 | Servidor em `127.0.0.1`; endpoint que dispara scan só aceita a mesma origem |

---

## 5. Design

### 5.1 Fonte por grandeza (aba Geral)

| Grandeza | Fonte | Tier |
|---|---|---|
| RPM | OBD `0C` (ECM) | padrão J1979 |
| Velocidade | OBD `0D` | padrão |
| Temp. líquido | OBD `05` | padrão |
| Borboleta | OBD `11` (também `45`, `47`, `4C`) | padrão |
| Temp. ar admissão | OBD `0F` | padrão |
| MAF | OBD `10` | padrão |
| Carga | OBD `04` / `43` | padrão |
| STFT / LTFT | OBD `06` / `07` | padrão |
| Avanço de ignição | OBD `0E` | padrão |
| O2 B1S1 / B1S2 | OBD `14` / `15` | padrão |
| Tensão do módulo | OBD `42` | padrão |
| Pulso de injeção, MAP | — | indisponível neste veículo |

`PID_TABLE` em `obd2.py` hoje cobre só 04 05 0C 0D 0F 10 11 2F 42 46. Faltam
06, 07, 0E, 14, 15, 43, 44, 45, 47 e 4C, com testes de decoder.

Tiers: `padrão` (SAE J1979), `confirmado` (✅ no tracker), `estimado` (tabela
ESM, sem referência independente), `cru` (sem interpretação), `indisponível`.

### 5.2 Fonte por grandeza (aba CVT)

| Campo | Origem | Tier |
|---|---|---|
| Rotação (conferência) | TCM `[6,7]÷8` | confirmado |
| Velocidade (conferência) | TCM `[4]` (e `[3]`) | confirmado, ver A9 |
| Marcha P/N/D/R | TCM nibble alto de `[54]` | confirmado*, ver 8 |
| Ré | TCM `[40]==0x5A` | confirmado* |
| Temp. ATF | TCM `[30]` pela tabela ESM | **estimado** |
| Lock-up, pressão, relação, deslizamento | `[38]` etc. | **cru** (🔴) |
| Identificação | LID `0x80`, `0x82`, `0x83` | cru ASCII |

`*` dependem da decisão 1 da seção 8.

Os valores do TCM e do OBD aparecem lado a lado com a diferença, para o
usuário ver se batem.

### 5.3 Gateway e agendador

- O device ganha troca de módulo sem reconexão. Duas opções, a medir com
  `j2534-check` antes de escolher: (a) `set_ids` (já escrito, para e reinicia o
  filtro); (b) dois filtros de fluxo ativos (7E0/7E8 e 7E1/7E9) e trocar só o
  ID de envio. A (b) evita parar/iniciar filtro a cada ciclo, mas depende de a
  DLL do GD101 aceitar dois filtros no mesmo canal. Nenhuma das duas foi
  testada no carro.
- Agendador em rodadas: grupo rápido (0C, 0D, 11 + LID 0x01 do TCM) a cada
  ciclo; grupo lento (05, 0F, 42, 06, 07, 04, 0E, 10, 14, 15) em rodízio, um ou
  dois por ciclo.
- Falha de um PID não derruba os outros (já é assim em `read_obd_live`).
- O poller registra a latência real de cada requisição, para as metas RNF1
  virarem números medidos.

### 5.4 Guarda de somente leitura (RF7)

Uma camada em volta de `send_recv` com lista de permissão:
OBD `01 02 03 07 09 0A`; KWP `10 C0` (abrir sessão), `3E`, `21`, `1A`, `13`,
`17`, `18`. Recusa qualquer outro SID, em especial `04 11 14 27 2E 31 34 36 3B`.
Teste offline garante que cada SID proibido levanta erro antes de chegar ao
adaptador.

### 5.5 Falhas (DTC): o que sabemos e o que testar

Estado atual:
- **ECM, OBD modo 03/07:** funciona. Hoje: nenhum DTC.
- **KWP `18`:** NRC 0x11 no ECM e no TCM, com e sem grupo. Descartado.
- O manual de serviço do Sentra diz que o TCM faz o diagnóstico OBD-II junto
  com o ECM e o DTC fica na memória dos dois, e que o TCM tem uma auto-diagnose
  própria, só da memória dele, lida pelo CONSULT. Portanto o modo 03 do ECM
  cobre os DTCs do CVT ligados a emissões, mas **não** os que são só do TCM.

Regra de exibição: a aba Falhas mostra por módulo um de quatro estados:
`nenhum DTC (leitura validada)`, `N códigos`, `leitura não suportada (NRC)`,
`não testado`. Para o CVT, "sem falhas" só aparece se o método estiver
validado.

Experimentos, em ordem, primeiro por CLI (`probe-dtc`) e só depois na tela:

| # | Experimento | Risco | Observação |
|---|---|---|---|
| H1 | OBD `03`/`07`/`0A` com endereço físico 0x7E1→0x7E9 | baixo | TCM é módulo de emissões; resposta não garantida |
| H2 | OBD `03` por broadcast funcional 0x7DF: ver quem responde | baixo | mostra se o TCM responde sozinho |
| H3 | KWP `13` e `17` (ISO 14230-3, leitura) sob sessão `C0` | baixo | aprovado (seção 8) |
| H4 | Reanálise offline dos LIDs `0x11` e `0x13-0x21` do TCM | nenhum | já suspeitos de contador/histórico; sem falha no carro não há como validar |
| H5 | SID `A3` (comunidade: "Read Time of DTCs") | **desconhecido** | aprovado pelo usuário, **com condições** (abaixo); semântica não documentada |

**Condições do H5 (`A3`)**, porque a semântica é desconhecida e `AGENTS.md`
exige revisão de segurança para o que não é leitura comprovada:
1. Só depois de H1, H2 e H3 terem sido registrados.
2. Carro parado, em P, freio de mão puxado; uma requisição por vez, sem parâmetros além do mínimo, só no ECM e no TCM.
3. Sessão `C0` já aberta, como nos outros testes. Nenhum outro SID de apoio.
4. Parar na primeira resposta inesperada (qualquer coisa que não seja positiva ou NRC) e registrar o cru.
5. `A3` **não entra** na lista de permissão geral (5.4). Existe só dentro do comando `probe-dtc`, atrás de uma flag explícita (`--allow-a3`).
6. Resultado vai para `docs/` como hipótese não verificada.

Limite: sem um carro com falha real (ou uma segunda ferramenta para comparar),
"resposta positiva sem códigos" é ambíguo. Não provocar falha para testar.

### 5.6 Scan sob demanda

O canal é único, então o scan **pausa o live** (a tela avisa). Etapas:

1. Presença dos módulos (catálogo `NISSAN_MODULES`; é catálogo Nissan, não descoberta universal).
2. ECM por OBD: bitmaps de PIDs, snapshot dos PIDs suportados, DTCs `03`/`07`/`0A`, Cal ID e CVN. VIN marcado "não suportado" (A4).
3. TCM: identificação (`80`, `82`, `83`), snapshot do LID 0x01 decodificado **e** cru, DTC conforme 5.5.
4. Outros módulos (BCM, IPDM, EPS, painel, 0x71E): presença e identificação; sem DTC.

Saída: `logs/scan_<ts>.json` (cru + decodificado + estado de cada leitura) e a
aba Scan com resumo. Nada de limpeza de códigos na interface.

### 5.7 Frame v2 e tela

```json
{"schema": 2, "ts": 1794779000.1, "conn": true, "data_source": "j2534",
 "modules": {"ecm": {"status": "ok", "age_ms": 80},
             "tcm": {"status": "stale", "age_ms": 2400, "error": "timeout"}},
 "values": {"rpm": {"value": 710, "unit": "rpm", "source": "obd:0C",
                    "tier": "padrao", "age_ms": 80, "raw": "410c0b18"}},
 "cvt": {"gear": {"value": "P", "tier": "confirmado", "raw": "0x19"}}}
```

Mantém `rpm`, `vsp`, `ect`, `tps` planos (RF9). A tela: abas Geral, CVT, Falhas,
Scan; selo de tier em cada card; card obsoleto fica esmaecido com o tempo;
cabeçalho conforme RF4.

---

## 6. Plano em fases

| Fase | Entrega | Critério de aceite |
|---|---|---|
| F0 | Higiene: `.gitattributes` (LF), commits separados do trabalho pendente, `session_log_20261115.md`, redirecionar saída de `car_session.py` para `logs/`, corrigir A7/A8 no analisador | `git diff` sem ruído de EOL; testes verdes |
| F1 | Dashboard por OBD no ECM (corrige o dia): `PID_TABLE`, poller, frame v2, cards com motivo | Mock: nenhum card "—" para PIDs suportados. **No carro, em marcha lenta:** RPM ~710, ECT ~94 °C, TPS, tensão batem com o scan de hoje |
| F2 | TCM no mesmo poller sem reconectar; aba CVT | Ciclo ≤ 500 ms medido; defasagem TCM↔OBD ≤ 100 ms; latências gravadas na captura |
| F3 | Guarda RF7 + scan sob demanda + abas Falhas e Scan | Scan completo gera JSON; SIDs proibidos barrados em teste |
| F4 | `probe-dtc` com H1-H3 (só após aprovação) | Resultado cru de cada hipótese registrado em `logs/` e `docs/` |
| F5 | Etapa 13 com dashboard e `--capture` ligados, em movimento | VSP > 0, ré, lock-up registrados; analisador sem falsos alertas |

Cada fase termina com commit próprio. Nada vai para o carro antes de passar
nos testes offline.

---

## 7. Testes

- **Fixtures** novas, vindas de hoje: respostas OBD de `full_scan_20261115_184513.txt`, LID 0x01 do TCM em P/N/D/R, ECM `001b0000` (regressão do bug).
- **Unitários:** decoders dos PIDs novos; `read_obd_live` com NRC e timeout; agendador de rodadas; frame v2; guarda de SIDs; compensação de defasagem no analisador.
- **Mock multi-módulo:** ECM e TCM respondendo no mesmo canal, com `set_ids`.
- **Playwright** (já existe em `tests/browser`): cards preenchidos, estados obsoleto/indisponível, troca de abas, aviso de scan.
- **No carro:** checklist por fase (seção 6). Hoje nada do caminho `--hardware` novo foi validado.

---

## 8. Decisões (respondidas em 2026-11-15)

| # | Decisão | Resposta |
|---|---|---|
| 1 | Promover a ✅ | **Marcha `[54]` e ré `[40]`: sim.** **ATF `[30]` fica "estimado"** até haver referência independente. Atualizar o tracker na F0 |
| 2 | Testes de DTC do TCM | **H1/H2 aprovados. H3 (`13`, `17`) aprovado. H5 (`A3`) aprovado com as condições da seção 5.5** |
| 3 | Chaves planas da API | **Manter** `rpm`, `vsp`, `ect`, `tps` junto do frame v2 |
| 4 | Scan e leitura ao vivo | **Scan pausa o live**; a tela avisa durante a execução |
| 5 | Etapa 13 (estrada) antes ou depois da F1 | **Em aberto.** Sugestão: depois da F2, para já capturar com o TCM no mesmo poller |

Nota sobre a decisão 1: `tcm_lid01.py` já trata o ATF como confirmado no
docstring. Ao implementar, ajustar o docstring e a saída do decoder para
`estimado`.

---

## 9. Fontes

- Logs e docs do próprio repositório (citados nas seções 1-2).
- Manual de serviço Nissan Sentra, "On Board Diagnostic (OBD) System", sistema de controle da transmissão: OBD-II feito pelo TCM junto com o ECM e auto-diagnose própria do TCM. https://manuals.autorepairshq.com/Nissan-Datsun/2009/Sentra%20L4-2.0L%20%28MR20DE%29/Repair%20and%20Diagnosis/Powertrain%20Management/Transmission%20Control%20Systems/Description%20and%20Operation/On%20Board%20Diagnostic%20%28OBD%29%20System/Introduction
- Sentra B16, "Diagnosis System (TCM)": modos de diagnóstico do TCM. https://www.nisentra.com/diagnosis_system_tcm_-2897.html
- SIDs do KWP 2000 (ISO 14230): 0x13, 0x17, 0x18. https://www.ime-actia.de/en/?p=5089
- Wiki da comunidade, KWP/14230 Nissan: `$17` e `$A3`. **Não oficial; tratar como pista.** https://nissanecu.miraheze.org/wiki/C2_14230
- Fórum RomRaider, KWP2000/ISO15765 em Nissan 350Z (`A3` provavelmente ligado a DTC). **Não oficial.** https://mailserver.romraider.com/forum/viewtopic.php?p=163146

## Resultados do teste no carro (2026-11-16, parado)

- Bug "velocidade = RPM" confirmado e corrigido (resposta atribuída por serviço, sem conferir o PID ecoado).
- Todos os PIDs OBD declarados responderam; P/R/N/D e ré do TCM confirmados; pausa/retomada do scan OK.
- Pulso do injetor: não existe via LID 0x21 neste ECM (14 LIDs respondem, todos strings de identificação).
- SID A3: NRC 0x11 no ECM e no TCM.
- **Hipótese (não validada):** TCM responde `17 FF 00` (em sessão `10 C0`) com `57 03 07 25 f1 d0 00 a7 17 22 f1`
  = P0725, U1000, P1722. O byte de status (f1/a7) fica cru, sem interpretação. Só aparece na UI como "HIPÓTESE";
  lista vazia continua nunca sendo "sem falhas". Falta confirmar com outra ferramenta (ex.: Consult).
- Scan: módulos que ignoram `3E` agora são detectados por `10 C0` (campo `probe` no resultado).
- `tcm_every` passou de 3 para 1: o câmbio é lido em todo ciclo (ciclo ~270 ms nos logs; skew esperado ~0). Confirmar no carro.
- Pendente: teste em movimento (relação, pressão de linha, lock-up), offset de vsp_tcm (1 km/h parado).

## Varredura do serviço 0x22 (2026-11-18)

- Motivo: aparelho de terceiros mostra "TCM · EIXOS" (eixo A, eixo B, saída) com pedidos `7E1;1EBC`, `7E1;1EC1`,
  `7E1;1EC0` (formato real desconhecido). É o dado que falta para a relação do CVT.
- Em 2026-10-23 o `scan-dids` varreu só F180-F1AF no TCM, sem sessão, e deu 0x11 (serviço não suportado).
- Novo `scan-22`: só `10 C0` + `22 <DID>`, atrás da guarda (0x22 liberado só por `extra_allowed`; escritas seguem
  bloqueadas), para na hora se o serviço não existir, regrava o JSON a cada DID. Resultado cru, sem interpretação.
