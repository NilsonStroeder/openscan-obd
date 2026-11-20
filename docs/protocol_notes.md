# Notas de protocolo

> Estas notas incluem uma trilha de pesquisa específica do Nissan Sentra/CVT,
> que é o veículo de teste atual. Elas registram experimentos e hipóteses e
> não definem o escopo do produto: o scanner é geral e extensível, com suporte
> amplo dependente de validação por veículo, ECU e adaptador.

## Pilha

```
Aplicação (openscan_obd)
    UDS        — ISO 14229-1
    ISO-TP     — ISO 15765-2 (segmentação de mensagens >8 bytes em frames CAN)
    CAN        — ISO 11898, 500 kbps tipicamente no barramento de diagnóstico Nissan
    J2534      — API passthru (SAE J2534-1) — é o que o driver do GD101 deve expor no Windows
```

## Serviços UDS relevantes (ISO 14229-1)

| SID    | Nome                        | Uso                                   |
|--------|-----------------------------|----------------------------------------|
| 0x10   | DiagnosticSessionControl    | Entrar em sessão estendida/programação |
| 0x11   | ECUReset                    | Reset do módulo                        |
| 0x19   | ReadDTCInformation           | Ler códigos de falha                   |
| 0x22   | ReadDataByIdentifier         | Ler parâmetros (DIDs)                  |
| 0x27   | SecurityAccess               | Seed/key para desbloquear funções protegidas |
| 0x2E   | WriteDataByIdentifier         | Escrever parâmetros                    |
| 0x31   | RoutineControl                | Executar rotinas (ex.: calibração)     |
| 0x3E   | TesterPresent                  | Manter sessão viva                     |

## Sobre "desbloqueio de módulo" (0x27 SecurityAccess)

SecurityAccess é seed/key: a ECU manda um "seed" e espera uma "key"
calculada por um algoritmo que o fabricante mantém fechado. Isso é
diferente de ler DIDs — envolve ou (a) descobrir o algoritmo por
engenharia reversa do firmware/software (fora do escopo deste projeto
pelos motivos já discutidos), ou (b) usar seeds/keys já publicados
por pesquisadores para módulos específicos, quando existem e são de
conhecimento público. Tratar com cautela: alguns desbloqueios alteram
parâmetros de segurança/emissões do veículo — documentar bem o que cada
rotina faz antes de executar em um carro real.

## GD101 — a confirmar

- [ ] Responde a comandos AT via serial (modo ELM327/STN)?
- [ ] Se não, qual DLL de driver J2534 ele instala no Windows?
- [ ] Baudrate/porta COM ao conectar

## Plano de captura (sniffing passivo)

Objetivo: descobrir quais IDs/DIDs CAN correspondem a dados do CVT,
observando o tráfego real gerado pelo Consult-III Plus genuíno — sem
tocar no binário dele.

### Passo a passo

1. Conectar o GD101 na porta OBD-II do carro, ligação chave na posição II
   (ou motor ligado, se for ler dados dinâmicos tipo temperatura/RPM).
2. Confirmar modo (rodar `elm_probe.py` antes, se ainda não confirmou).
3. Rodar a captura em paralelo:
   ```
   python -m openscan_obd.cli capture --mode serial-elm --port COM3
   ```
4. Em outra janela/dispositivo, abrir o Consult-III Plus normalmente e
   navegar pelas telas de interesse (CVT: temperatura, pressão de linha,
   DTCs, dados ao vivo).
5. A cada tela/leitura relevante, voltar no terminal da captura e apertar
   ENTER, digitando uma descrição curta (ex.: "entrei na tela CVT live data").
   Isso grava uma linha MARKER com timestamp no mesmo CSV.
6. Ctrl+C pra parar. O log fica em `logs/capture_<timestamp>.csv`.

### Limitação a confirmar na prática

Se o GD101 só tiver UMA conexão física disponível, pode não dar pra rodar
o sniff E o Consult-III ao mesmo tempo no mesmo adaptador. Alternativas:
- Usar um segundo adaptador (até um ELM327 genérico barato) só pra sniff,
  enquanto o GD101 roda o Consult-III
- Ou, se o GD101 suportar, um "splitter" físico de OBD-II (existem cabos Y)

### Análise pós-captura

Depois da captura, o próximo módulo (`analyze.py`, a construir) vai:
- Agrupar frames por `can_id`
- Mostrar quais IDs tiveram mudança de valor nos segundos ao redor de
  cada MARKER
- Isso reduz o universo de "centenas de IDs no barramento" pra "um
  punhado de candidatos por marcação"

## Transporte — decisão (2026-10-22)

`udsoncan.connections.J2534Connection` é nativo da lib e não precisa de
wrapper ctypes próprio. Requer:
- Driver J2534 do GD101 instalado no Windows
- Caminho da DLL (ver Painel de Controle → "<adaptador> J2534 Configuration",
  ou procurar em Program Files)

Isso só funciona pra COMUNICAÇÃO ATIVA (ler DIDs enviando request/
response). Pra SNIFFING PASSIVO (capture.py), ainda é preciso confirmar
se a API J2534 do GD101 permite modo "monitor" (PassThruStartMsgFilter
sem transmitir) ou se só dá pra sniffar em modo ELM327/AT.

Próxima vez que estiver no carro: rodar `examples_read_vin.py` primeiro
(ajustando o DLL_PATH) só pra validar que a conexão J2534 básica
funciona, antes de tentar achar os IDs do CVT.

## Descoberta importante (2026-10-23): GODIAG_PT32.dll é 32-bit

Erro real por trás do `RuntimeError('OSError, 8')` do udsoncan:
```
OSError: [WinError 193] %1 não é um aplicativo Win32 válido
```

Causa: `GODIAG_PT32.dll` é uma DLL de 32 bits (confirma o "32" no nome), e
um processo Python 64-bit não consegue carregar DLL 32-bit via ctypes —
é uma limitação do carregador do Windows, não um bug no projeto.

Solução: rodar este projeto com um **Python de 32 bits** dedicado (venv
separado). Instruções completas em arquivo/PRIMEIRO_TESTE_NO_CARRO.md.

Isso é uma limitação comum de adaptadores J2534 — praticamente todo
fabricante só disponibiliza DLL 32-bit.

## Descoberta importante (2026-10-23): captura passiva (ATMA) nunca funcionou

Três tentativas de captura (`capture_20261023_073937.csv`,
`capture_20261023_080430.csv`, `capture_20261023_080521.csv`) resultaram
na mesma coisa: nenhum `CAN_FRAME`/`CAN_RAW` real, só um único `?` (ou
nada) e os marcadores. Duas causas encontradas no código do
`SerialElmSniffer.connect()`:

1. **`ATSP0` (protocolo automático)** era enviado antes do `ATMA`.
   Auto-detecção de protocolo depende de uma troca real de
   requisição/resposta OBD pra descobrir baud/formato do ID — isso não
   existe em modo de monitor passivo. Sem protocolo fixado, o adaptador
   não sabe decodificar o barramento e o `ATMA` falha. **Fix**: trocado
   por `ATSP6` (ISO 15765-4 CAN, 11-bit, 500 kbps) — confirmado como o
   protocolo real do carro pelo teste com o J1979 Diagnostic Tool
   (`ECU#1 ID 07E8`).
2. **`ATS0` (espaços desligados)** era enviado no preâmbulo, mas o
   parser do `analyze.py` espera ID e bytes separados por espaço — com
   `ATS0` a linha real viria colada (`7E8034100BE`) e nunca casaria com
   o regex, mesmo que o `ATMA` funcionasse. **Fix**: trocado por `ATS1`.

Também adicionado `ATH1` (garante que o ID do frame apareça na linha —
sem headers, não tem como saber de qual módulo veio cada frame).

`analyze.py` também ficou mais tolerante: regex de ID agora aceita 3-8
dígitos hex (antes só 3 ou exatamente 8), e linhas de ruído conhecidas
do adaptador (`ATMA`, `OK`, `>`, `SEARCHING...`, `BUFFER FULL`, etc.)
são ignoradas silenciosamente em vez de contarem como "não reconhecida".

**Ainda não testado no carro** — correção feita só a partir da leitura
do código e do comportamento documentado do dialeto ELM327/AT. Validar
na próxima sessão.

## Plano pra V2 no carro (carro fica na rua — ser rápido)

Carro na rua = pouco tempo seguro por sessão. Ordem sugerida, do mais
rápido pro mais demorado, pra conseguir parar em qualquer ponto e já
ter aproveitado algo:

1. **Plugar o GD101, chave na posição II.** (não precisa ligar o motor
   pra esta parte)
2. **Rodar a captura corrigida** (1 comando, já roda em background
   escutando):
   ```cmd
   python -m openscan_obd.cli capture --mode serial-elm --port COM9
   ```
   Confirmar visualmente que aparecem linhas `CAN_RAW` de verdade na
   tela (não só silêncio) — isso já valida se o fix funcionou, mesmo
   sem fazer mais nada.
3. **Se aparecer tráfego real**: apertar ENTER + marcar 2-3 ações
   rápidas (ex.: pisca-alerta ligado/desligado — não precisa nem ligar
   o motor) só pra ter prova de correlação. Ctrl+C, guardar o log.
4. **Se der tempo/segurança**: rodar `experimental/examples_scan_addresses.py`
   (varredura dos 8 endereços padrão 0x7E0-0x7E7) — **fechar a
   captura antes**, já que o GD101 só aceita uma conexão por vez. Isso
   pode achar o endereço do TCU (0x7E1/0x7E9) sem precisar sniffar.
5. Documentar no fim do dia: o que respondeu, o que não respondeu, e
   colar uma linha de exemplo real de `CAN_RAW` aqui nestas notas (pra
   eu poder ajustar `_RAW_LINE_RE` se o formato real for diferente do
   que assumi).

Não precisa fazer tudo numa sessão só — cada item acima já é útil
isoladamente.

## Fonte confiável pro formato real do ATMA (2026-10-23)

Encontrei a documentação do driver **can327** do kernel Linux
(`docs.kernel.org/.../can327.rst`) — ele implementa suporte nativo a
adaptadores ELM327/STN em modo monitor, então documenta o formato de
linha com precisão de driver, não achismo de fórum:

```
123 8 DEADBEEF12345678
```
`ID (hex)` + espaço + `DLC (decimal, 0-8)` + espaço + `dados em hex
contínuo (sem espaço entre bytes)`. O campo DLC só aparece com `ATD1`
ligado — sem ele, firmwares antigos (<1.3) nem sempre deixam claro onde
os dados terminam numa linha truncada (`BUFFER FULL`).

Ações tomadas:
- Adicionado `ATD1` ao preâmbulo de `capture.py`, mas como comando
  **opcional** (se o firmware responder `?`, loga aviso e segue sem
  ele, não aborta a conexão — não sabemos se a v1.3a deste GD101
  suporta).
- `_RAW_LINE_RE` em `analyze.py` reescrito pra aceitar DLC opcional e
  dados contínuos (sem espaço), mantendo tolerância ao formato
  espaçado como fallback.
- Fonte completa: https://docs.kernel.org/6.3/_sources/networking/device_drivers/can/can327.rst.txt

## Outras fontes encontradas, só pra registro (nada incorporado ainda)

- `github.com/jakka351/GenericDiagnosticTool` — ferramenta J2534 em C#
  (KWP2000/UDS, foco em Ford/Mazda/JLR/Volvo). Tem bruteforcer de
  DID/PID (legítimo — só testa quais IDs respondem) e também um
  bruteforcer de SecurityAccess (0x27) citando chaves JLR obtidas de
  software proprietário de terceiros — **não vamos seguir essa linha
  aqui**, mas a ideia do bruteforcer de DID (tentar uma faixa de DIDs
  genéricos e ver quais respondem com dados, sem precisar de
  SecurityAccess) é legítima e pode valer a pena implementar como
  próximo passo depois de achar o endereço do TCU.

## Compilado da sessão de testes reais — 23/10/2026

### 1. Captura passiva (ATMA) — corrigida no código, mas aparentemente não funciona neste hardware

Depois dos fixes (ATSP0→ATSP6, ATS0→ATS1, +ATH1, +ATD1 opcional), o
preâmbulo passou a responder `OK` limpo em TODOS os comandos (confirmado
com debug ao vivo, inclusive com o motor ligado). Mesmo assim, o `ATMA`
não produziu **nenhuma** linha de dado em nenhuma das tentativas — nem
um `?`, nem ruído, nada, por ~40s com o motor ligado (quando deveria
haver tráfego CAN intenso).

**Conclusão provisória**: o GD101 provavelmente tem uma camada de
emulação ELM327 rasa, que entende e confirma os comandos AT (inclusive
`ATMA`), mas não implementa de fato o streaming de monitor passivo —
plausível em cabos pensados primariamente pra uso via J2534 ativo, com
o modo ELM sendo só compatibilidade superficial. Não deu pra confirmar
100%, mas é a explicação mais consistente com os dados.

**Impacto**: sniffing passivo via este adaptador pode ser um beco sem
saída. O caminho que funciona de ponta a ponta é comunicação ATIVA via
J2534 (UDS request/response). ⚠️ Correção 2026-11-05: só o J1979
Diagnostic Tool do fabricante foi validado; o VIN nunca foi lido por este
código (6 `vin_test` e 4 `full_scan` falharam; ECM responde `22 F190` com
NRC 0x12).

### 2. Varredura de endereços padrão (SAE J2012/ISO15031) — funcionou, com resultado real

`experimental/examples_scan_addresses.py` testou os 8 pares padrão (0x7E0-0x7E7). Um
teste de sanidade com endereço bogus (0x7F7/0x7FF) confirmou que o
driver FILTRA corretamente por ID (deu timeout limpo) — então os
resultados abaixo são confiáveis:

- `0x7E0`/`0x7E8` (motor): respondeu, negado (`SubFunctionNotSupported`)
  — já conhecido de antes.
- `0x7E1`/`0x7E9` (candidato a TCU): **respondeu** (não deu timeout!) —
  há um módulo real ouvindo nesse endereço.
- `0x7E2` a `0x7E7`: todos deram timeout — nada ali.

**Bug encontrado no script**: ele só conta como "respondeu" quando a
leitura de VIN tem SUCESSO total — uma resposta negativa (que ainda
assim prova que tem ECU lá) cai junto com timeout no resumo final
("Nenhum endereço respondeu"). Precisa ser corrigido pra distinguir
"recusou" de "não existe". Ainda não corrigido.

### 3. O módulo em 0x7E1/0x7E9 recusa tudo que tentamos

- `DiagnosticSessionControl` (sessão estendida): `SubFunctionNotSupported` (0x12)
- `ReadDataByIdentifier`, varrido em 48 DIDs genéricos (0xF180-0xF1AF): **todos** deram o mesmo `ServiceNotSupported` (0x11), sem variar por DID — confirma que é bloqueio de serviço/sessão, não de DID específico.
- `ReadDTCInformation` (leitura de códigos de falha, 0x19): também `ServiceNotSupported` (0x11)

**Hipótese principal**: esse módulo implementa um subconjunto bem
restrito de UDS (ou nem é o TCU/CVT de verdade — o endereçamento padrão
SAE nem sempre é seguido à risca, principalmente em carros no limite do
período de adoção, como este Sentra 2010). É bem possível que os dados
reais do CVT só sejam acessíveis via protocolo proprietário CONSULT da
Nissan, não via UDS genérico — o que explicaria por que apps genéricos
(inclusive o nosso) não conseguem e só ferramentas específicas tipo
CVTz50/Consult-III conseguem.

**Isso NÃO muda o escopo do projeto**: continuamos sem decompilar o
Consult-III nem caçar seed/key. Só estamos documentando honestamente um
limite técnico real que apareceu na prática.

### 4. Pesquisa no GitHub/kernel que ajudou de verdade

Driver `can327` do kernel Linux documentou o formato real de linha do
modo monitor ELM327 (ID + DLC decimal opcional + dados em hex contínuo)
— isso corrigiu um erro de suposição no `_RAW_LINE_RE` do `analyze.py`
que estava errado desde o início (bytes não vêm separados por espaço).

### 5. O que ficou pronto hoje (código)

- `capture.py`: preâmbulo corrigido (ATSP6, ATS1, ATH1, ATD1 opcional) + debug temporário
- `analyze.py`: parser de CAN_RAW corrigido pro formato real (DLC opcional, dados contínuos) + filtro de linhas de ruído
- `dids.py`: GENERIC_DIDS expandido + STANDARD_ADDRESSES (tabela SAE)
- `experimental/examples_scan_addresses.py`: varredura dos 8 endereços padrão (tem o bug de contagem citado acima)
- `did_scan.py` + comando `scan-dids`: varredura de faixa de DIDs, só leitura, sem SecurityAccess
- `examples_read_tcu.py`, `examples_read_dtc_tcu.py`, `examples_sanity_bogus_address.py`: scripts pontuais de investigação de hoje
- `tests/test_capture_fake_serial.py` + `tests/test_did_scan_fake_client.py`: testes com hardware simulado (pegaram 1 bug de verdade na hora de escrever)

### 6. Próximos passos (não feitos ainda, em ordem de valor)

1. Corrigir o bug de contagem em `experimental/examples_scan_addresses.py` (distinguir "recusou" de "não existe")
2. Decidir se vale tentar sniffing passivo com OUTRO adaptador ELM327 genérico barato (não o GD101), já que o problema parece ser de hardware/firmware, não do nosso código
3. Considerar varrer endereços CAN fora da faixa padrão SAE (requer ou sniffing real — bloqueado — ou tentativa demorada, um por um, de uma faixa maior de IDs via UDS ativo)
4. Aceitar como hipótese de trabalho que os dados profundos do CVT podem só existir via protocolo proprietário Nissan, e documentar isso como limite conhecido do projeto (não como algo a contornar)

## PESQUISA DE FONTES — 23/10/2026 (análise antes de mais código)

Investigação focada em "como o CVTz50 realmente funciona", já que ele é a
prova viva de que os dados do CVT são acessíveis. ~15 fontes consultadas
(lista no fim). Conclusões:

### A) Correção de base: a transmissão estava ERRADA no projeto

O Sentra 2010 2.0 usa **JF011E / RE0F10A (CVT8)**, NÃO a JF015E/RE0F11A
(essa é a CVT7, de carros mais novos/menores). Toda busca anterior por
DIDs de "RE0F11A" estava mirando no transmissor errado.
- Fonte: múltiplos catálogos de peça (eBay/Amazon/Berkeley Standard) para
  "2007-2012 Nissan Sentra 2.0 -> JF011E RE0F10A".
- IMPORTANTE: o CVTz50 lista a **JF011E explicitamente como suportada**
  (CVT com step motor). Logo, o carro é atendido — a pergunta nunca foi
  "da pra ler?", e sim "qual o metodo certo?".

### B) Prova de alcançabilidade (o que isso ELIMINA)

O CVTz50 lê o TCM desse carro com **ELM327 comum, por CAN (ISO15765,
500k)**. Isso derruba três becos:
- NAO precisa decompilar o Consult-III.
- NAO precisa de K-line / CONSULT serial antigo. (As libs open-source de
  CONSULT — K11Consult, Arduino-Nissan-Consult-Library, Nissboard — são
  todas K-line serial, para Nissan PRE-CAN: Micra K11, Skyline R34. NAO
  se aplicam ao nosso caso CAN de 2010. Registrado pra não cair nesse
  rabbit hole.)
- NAO precisa de SecurityAccess (0x27) para LER dados ao vivo.

### C) Por que o protocolo do CVT é "mais complexo" (e por que falhamos)

O site oficial do CVTz50 exige o comando **`ATAL` ("Allow Long messages")**
e um ELM327 genuíno (chip PIC18F25K80, cristal 4MHz; testes de
autenticidade via ATPPS). O tutorial de ELM327 do Nissan Leaf confirma
que a sequência real para módulos Nissan por CAN é
`ATSP6` + `ATAL` + filtro de header (ATCRA).

**Interpretação fundamentada**: as respostas do TCM são mensagens LONGAS,
multi-frame (ISO-TP). Clones baratos de ELM327 montam mal o flow-control
dessas respostas longas -> falam com o motor (respostas curtas) mas não
com a transmissão. Não é "firmware velho", é incapacidade de remontar
multi-frame.

Consequências diretas pro nosso setup:
- **A favor**: o caminho J2534 do GD101 (via udsoncan) trata ISO-TP
  multi-frame NATIVAMENTE — não sofre a limitação do clone ELM327. Nesse
  ponto o GD101 é mais capaz que um ELM327 barato.
- **Explica o 0x7E1**: o módulo respondeu mas recusou 0x22/0x19/0x10 com
  ServiceNotSupported. Como os dados do CVTz50 são "equivalentes ao
  Consult-II" (protocolo mais antigo), a hipótese principal é que o TCM
  use o serviço **0x21 (ReadDataByLocalIdentifier, estilo KWP2000)** em
  vez do 0x22 do UDS moderno. NUNCA testamos 0x21. <-- proximo experimento

### D) O gap honesto

Ainda NAO temos os bytes exatos que o CVTz50 envia (serviço, header,
local identifiers). Duas formas de fechar isso:

- **Caminho A (decisivo, mas exige adaptador extra)**: instalar o CVTz50
  DEMO grátis (Android) + um ELM327 Bluetooth baratinho compatível
  (Konnwei KW902, Vgate iCar Pro, Viecar 4.0 — ~R$30-50). O GD101 NAO
  serve pro CVTz50 (é cabo USB/J2534 pra PC, não adaptador Bluetooth pra
  celular). O demo (1) prova se o CVT do carro é legível, e (2) se a
  gente capturar o tráfego app<->adaptador, vira a ESPECIFICACAO do nosso
  scanner. Captura do tráfego Bluetooth é um esforço à parte.
- **Caminho B (custo zero, usa o GD101 atual)**: testar 0x7E1 com serviço
  **0x21** em vez de 0x22, já esperando resposta longa/multi-frame.
  Experimento único e dirigido (não tentativa cega), alinhado ao objetivo
  de scanner próprio com o hardware que já temos.

### Fontes principais
- Manual de serviço oficial Nissan, seção CVT do Sentra (nicoclub service-manual): confirma TCM com K-LINE (pino 6) + CAN (pinos 31/32), DTCs do CVT legiveis via GST/OBD-II generico, diagnostico profundo via CONSULT-III.
- cvtz50.info/en/ e cvtz50.info/en/elm327/: requisitos de adaptador (ATAL, PIC18F25K80), suporte a JF010E/JF011E, parametros "equivalentes ao Consult-II".
- leaf-obd.readthedocs.io (tutorial ELM327): sequencia real Nissan CAN (ATSP6, ATAL, ATCRA, ATH1, ATS1).
- jackm/carhack (nissan.md): CAN IDs de carroceria de um Sentra 2010 @500k (confirma a taxa), mas nada de TCM/CVT.
- K11Consult, Arduino-Nissan-Consult-Library, Nissboard: CONSULT K-line serial, Nissan pre-CAN — nao aplicavel ao caso CAN.

## MAPA TIER B v0 — consolidado de 3 agentes de pesquisa (23/10/2026)

Pesquisa paralela (ABS/SRS, BCM/IPDM, CVT/TCM). Resultado consolidado:

### Conclusão mais importante: protocolo é KWP2000/CAN, serviço 0x21 (NAO UDS 0x22)
Confirmado por 3 fontes independentes (wiki nissanecu, lib gkbus, comportamento
do TCM no nosso carro). Os Nissan dessa era usam ISO 14230 / KWP2000 sobre CAN,
com serviço **$21 (ReadDataByLocalIdentifier)**, nao o $22 do UDS moderno.
Isso EXPLICA por que nosso did_scan (que usa 0x22) e o scan de enderecos
(0x22 VIN) falharam no 0x7E1: estavamos falando a lingua errada.
- DTCs: provavelmente $18 (readDtcByStatus KWP) ou $19 — testar ambos.
- Clear: $14.

### Headers candidatos (do Nissan Leaf, mesma era — INFERENCIA, validar no carro)
Fonte: NJbubo/leaf_can_bus_messages. Padrao Nissan: resposta = requisicao + 0x20.
Todos FORA da faixa OBD padrao 0x7E0-0x7E7 (confirma que Tier B exige header custom):
- ABS/VDC   → req 0x740 / resp 0x760
- SRS/Airbag → req 0x752 / resp ~0x772
- BCM       → req 0x745 / resp 0x765
- Meter     → req 0x743 / resp 0x763
- HVAC      → req 0x744 / resp 0x764
- EPS       → req 0x742 / resp ~0x762
- TCM/CVT   → 0x7E1 / 0x7E9 (CONFIRMADO presente no nosso carro, faixa SAE)
No ELM327: ATSH <req> + ATCRA <resp>. Valores do Leaf NAO confirmados pro B16;
proximo passo pratico = varredura ativa de 0x700-0x7FF no carro.

**Atualizacao 2026-11-05 (can_id_scan 2026-10-24 no B16):** EPS 0x742/0x762,
Meter 0x743/0x763, BCM 0x745/0x765 e IPDM 0x74D/0x76D respondem (+0x20).
O modulo 0x71E responde em **0x72E (+0x10)** — a regra +0x20 nao e universal;
o `discover` agora tenta +0x20 e +0x10. ABS 0x740, SRS 0x752 e HVAC 0x744 nao
responderam nos pares testados. Meter e IPDM estao no CAN neste carro.

### Arquitetura de barramento: SEM gateway central
Nissan ~2008-2010 liga os modulos em paralelo no CAN direto ao DLC (pinos 6/14).
NAO ha gateway/firewall filtrando acesso (ao contrario de europeus modernos).
Entao nao ha bloqueio de rede nos impedindo.

### O limitador REAL: divisao CAN vs K-line
A Nissan mistura protocolos no mesmo carro. Em alguns modelos da era, ECM/TCM
(e as vezes BCM) ficam no CAN, mas meter, HVAC, Smart Key e as vezes IPDM ficam
em K-line (Consult-II) — INALCANCAVEIS por ELM327/J2534 operando so em CAN.
Qual modulo esta em qual barramento NAO esta documentado pro B16 — tem que
verificar no carro (varredura + conferir FSM).

### Lacuna que nenhuma fonte publica fecha: LIDs + formulas
Os identificadores locais (quais $21 <LID> retornam o que) e as formulas de
conversao (escala/offset) de CADA modulo — inclusive os parametros do CVT
(temp, pressao, razao) — NAO existem em fonte aberta. CVTz50 e fechado.
Isso so sai de: (a) sondagem $21 no carro vendo o que decodifica, ou
(b) captura de ferramenta funcionando. Sem atalho de tabela pronta.

### Implicacoes diretas pro nosso codigo (a fazer, nao feito)
- did_scan.py usa 0x22 → precisa de variante 0x21 (KWP ReadDataByLocalId).
  udsoncan nao tem $21 de alto nivel, mas Connection.send(bytes)/wait_frame()
  permite mandar o request cru. Usar isso.
- experimental/examples_scan_addresses.py → estender pra faixa 0x700-0x7FF (nao so 0x7E0-7E7).
- O "scan completo" Tier A (OBD-II padrao) continua valido e independente disso.

### Experimentos priorizados pra proxima ida ao carro (curta, carro na rua)
1. TCM: ATSH 7E1 + `21 01` (e 21 02, 21 03...) — ver se volta `61 ...`. Valida 0x21.
2. Varredura 0x700-0x7FF com um ping KWP simples — mapear quais modulos respondem.
3. Nos que responderem, sondar $21 <LID> e $18/$19 (DTCs).

### Fontes
- https://nissanecu.miraheze.org/wiki/C2_14230 (KWP2000/ISO14230, serviço 0x21)
- https://github.com/NJbubo/leaf_can_bus_messages (headers Leaf)
- https://pypi.org/project/gkbus/ (KWP2000 sobre CAN, libs Nissan)
- https://automotivetechinfo.com/wp-content/uploads/2011/03/Nissan-CAN-Controller-Area-Networks-Advantages-Diagnosis-Repair.pdf (sem gateway central)
- https://nisscan.com/which-nds-software/ (mistura CAN vs K-line)
- https://leaf-obd.readthedocs.io/en/latest/tutorial/elm327.html

## DECISAO DE ARQUITETURA — 23/10/2026 (apos ler fonte do gkbus)

Avaliei libs KWP2000 existentes pra nao reinventar:
- **gkbus** (dmg210): KWP2000 ISO14230 sobre CAN+K-Line, bem estruturada. MAS o
  backend CAN dele e Scapy CANSocket = SocketCAN (Linux) ou PEAK/PCAN (Windows).
  **Nao fala J2534.** Nao serve pro GD101. (Codigo lido direto, confirmado.)
- **kwp2000-can** (EliasTuning): usa J2534, mas so variantes VAG (TP20) e BMW —
  transporte errado pro KWP2000-ISO-TP simples da Nissan.

**Conclusao: nao ha lib pronta pra "Nissan KWP2000-sobre-CAN via J2534".**
Construimos a camada, mas com o gkbus como GABARITO comprovado do empilhamento:
  hardware (frames CAN) -> transporte ISO-TP (tx_id, rx_id) -> protocolo KWP (0x21)

**Chave da arquitetura**: o proprio J2534 ja faz o ISO-TP (flow control,
multi-frame). Por isso a leitura do motor funcionou. Entao NAO precisamos de
Scapy/SocketCAN. Stack pro nosso caso:
- conexao J2534 (via udsoncan) = transporte ISO-TP
- setar CAN IDs tx/rx por modulo (header): TCM 0x7E1/0x7E9, ABS 0x740/0x760, etc.
- mandar request KWP 0x21 cru via Connection.send(), ler resposta 0x61

### Plano de construcao aprovado
- **Tier A** — OBD-II padrao (modos 03/07 DTC, 01 dados ao vivo, 09 VIN, 04 clear).
  Universal, documentado, independente da descoberta Nissan. Decoders testaveis
  sem carro (DTC 2-byte -> P/C/B/U; PIDs; VIN). <- COMECANDO POR AQUI
- **Tier B** — sonda KWP 0x21 espelhando o gabarito gkbus, pra validar no carro.

### Refs de codigo
- gkbus: github.com/dmg210/gkbus (gkbus/transport/kwp2000_over_can_transport.py mostra o padrao ISO-TP tx_id/rx_id)
- kwp2000-can: github.com/EliasTuning/KWP2000-CAN (padrao J2534, protocolo VAG/BMW)

## ACHADO CHAVE — repo nissan-qashqai-can-info (23/10/2026)

Fonte: github.com/balrog-kun/nissan-qashqai-can-info — engenharia reversa
legítima de um Nissan Qashqai J10 (mesma era, mesmo esquema de diag Nissan).
NÃO usei os arquivos de seed/key do repo (calc_key/keydata) — fora de escopo.
A documentação de frames/PIDs é que importa, e ela corrige nossos erros:

### Por que o TCM deu 0x80 a TODOS os LIDs: VARREMOS A FAIXA ERRADA
O doc diz textualmente: no serviço 0x21, "não há bitmask de PIDs suportados
para os LIDs DEPOIS de 0x80". Todos os LIDs úteis documentados estão na
faixa **0x80-0xFF** (0x80, 0x81=VIN, 0x82, 0x84, 0xF0, 0xFE, 0xFF...), não
em 0x00-0x20. Nossa sonda varreu 0x00-0x20 → por isso só 0x80 (rejeição).
CORREÇÃO: varrer 0x21 em 0x00-0xFF, com foco em 0x80-0xFF.

### Sessão CONFIRMADA: alguns módulos exigem StartDiagnosticSession 0xC0
O doc: endereço 742 (EPS) "requires diagnostic session 0xc0". Confirma a
hipótese da sessão. Nossa discover_session já tenta 0xC0. Bom.

### Os endereços que "chutamos" do Leaf estão PLAUSÍVEIS
Qashqai usa 7e0 (motor), 742 (EPS), 745/74d (BCM/IPDM) — batem com os
nossos candidatos do Leaf (742 EPS, 745 BCM). Então "ausente" no nosso
scan provavelmente NÃO é endereço errado, e sim: precisam de sessão antes,
ou de um request diferente de "0x21 0x00". Re-testar com sessão + LID real.

### Estrutura por serviço (deste Nissan):
- Serviço 0x22 (2-byte PID, 0x2000+): usado pelo MOTOR p/ dados ao vivo
  (0x2001 temp, 0x2002 RPM, 0x2005 tensão, 0x2006 hodômetro...). O TCM
  nosso recusou 0x22 (ServiceNotSupported) → TCM é 0x21, não 0x22.
- Serviço 0x21 (1-byte LID, faixa 0x80-0xFF): usado por BCM/EPS/outros p/
  identificação e dados. É o caminho do TCM.

### Broadcast (passivo, sem sessão): frames de câmbio
Modelos automáticos transmitem info de câmbio nos frames 0x176, 0x41f,
0x421 (doc, linha 6). Opção de leitura passiva — se resolvermos o sniff
CAN cru via J2534 (o ATMA do ELM falhou).

### Correções acionáveis pra próxima ida ao carro:
1. TCM: discover_session (inclui 0xC0) -> varrer 0x21 em 0x00-0xFF (foco 0x80+).
2. Módulos "ausentes": re-probe COM sessão antes de desistir.
3. Motor: tentar 0x22 2-byte PIDs 0x2000-0x20FF (dados ao vivo enhanced).

## ANGULO "CARRO MUNDIAL" — irmãos globais a garimpar (23/10/2026)
O Sentra B16 e seu CVT Jatco rodam em muitos modelos pelo mundo. Procurar
RE sob TODOS esses nomes aumenta muito a chance de achar os LIDs do TCM:
- Plataforma/sedan: Sentra, Sylphy, Bluebird Sylphy, Pulsar, Tiida, Versa, Latio, Note
- CVT Jatco (JF011E/RE0F10A e primos JF015E/JF016/017): Qashqai, X-Trail, Juke,
  Rogue, Murano, Altima, Teana, Wingroad
- Aliança: Renault (Koleos, Megane CVT), Mitsubishi (Outlander, Lancer CVT), Suzuki Kizashi, Chery
- Base de endereçamento/bits: jackm/carhack/nissan.md (é de um SENTRA 2010 = nosso carro)

## FECHAMENTO DA GARIMPAGEM (23/10/2026)
Vasculhei o indice awesome-automotive-can-id + repos: carhack (Sentra 2010 =
nosso carro, so broadcast de carroceria), opendbc (so sinais rasos), qashqai
(melhor fonte de ESTRUTURA de diagnostico, sem CVT), leaf repos, 370Z. 
CONCLUSAO FIRME (confirmada por exaustao): o mapa de LIDs profundos do CVT
(temp/pressao/razao) NAO existe publico — so no CVTz50 fechado.

O que ESTA publico e aproveitavel:
- Broadcast de carroceria/powertrain: speed, marcha, controles (carhack, opendbc) -> leitura passiva
- Estrutura de diagnostico Nissan: servico 0x21 LIDs 0x80-0xFF, sessao 0xC0, servico 0x22 2-byte no motor (qashqai)
- OBD-II padrao: ja funciona (Tier A)

As DUAS metades do projeto, definidas:
- ALCANCAVEL (temos os dados): scanner geral = OBD-II padrao + DTCs por modulo
  (0x21 corrigido) + dados enhanced do motor (0x22 2-byte) + sinais de broadcast.
- ENGENHARIA REVERSA (sem mapa publico): params profundos do CVT. Rotas: 
  (A) capturar CVTz50 [precisa ELM327 BT], ou (B) forca bruta no carro
  [sessao 0xC0 -> varrer 0x21 0x80-0xFF -> correlacionar mexendo no carro].

## !!! DESTRAVE DO CVT — 23/10/2026 16:36 !!!
A sessao 0x10 subtipo 0xC0 LIBERA a leitura 0x21 do TCM (0x7E1/0x7E9).
Antes (sessao 0x81) dava 0x80 em tudo; com 0xC0 vieram 33 LIDs com dado.
LIDs sem dado agora retornam 0x12 (subFunctionNotSupported = "nao existe"),
confirmando que 0xC0 e a sessao certa.

### Mapa inicial dos LIDs do TCM (fonte: leitura real 0x21 em sessao 0xC0)
- 0x01, 0x02 : blocos de DADOS AO VIVO (muitos bytes variaveis) <- ALVO p/ temp/pressao/razao/RPM
- 0x10, 0x11, 0x12 : mais dados ao vivo / contadores
- 0x13-0x21 : blocos grandes com estrutura repetida "f3 05 30 00 ..." -> provavel FREEZE-FRAME / historico de DTC
- 0x80 : identificacao (ASCII "...APY...") - part number
- 0x83 : identificacao (ASCII "ZJ80B...") 
- 0x81, 0x84, 0xF0, 0xF1, 0xFE, 0xFF : 0xFF (vazios/nao usados)
- 0x20, 0x40, 0x60 : praticamente zeros

### Proximo: correlacao (Caminho B) pra LABELAR os bytes de 0x01/0x02
Snapshots em estados contrastantes -> compare -> byte que muda = a grandeza.
Contexto do motor no momento da leitura: ~85C, ~730 RPM, 14.2V, borboleta ~13%.

## MAPA DO LID 0x01 (TCM) — candidatos por correlacao (23/10/2026)
Fonte: compare marcha_lenta vs acelerado (sessao 0xC0, 0x21 LID 0x01).
Contexto motor: 84C, ~719 rpm lenta -> ~3000 rpm acelerado.
Posicoes = offset no data apos o 0x61 (pos 0 = eco do LID = 0x01).

CANDIDATOS FORTES (cross-check com dados do motor):
- byte 9  = TEMP FLUIDO CVT. 0x7C=124 -> 124-40 = 84C (= temp motor quente).
            Formula provavel A-40 (C). CONFIRMAR com contraste frio/quente.
- byte 6  = RPM entrada/primaria. 22 (lenta) -> 93 (acel). Escala ~x32:
            22*32=704 (~719 motor), 93*32=2976 (~3k). byte 15 espelha (22->93)
            = provavel RPM secundario/saida. CONFIRMAR com mais rotacoes.

CANDIDATOS A INVESTIGAR (mudaram com rotacao, significado a definir):
- bytes 19-23: saem de 00 -> 17 17 17 18 (so com aceleracao) = velocidade/slip?
- bytes ~44-54: valores 16-bit "02 xx" que variaram (02a0->022e, 026d->0250) = razao/pressao?
- byte 65: contador 06->07.

METODO p/ confirmar (proximas idas):
- frio x quente -> trava o byte 9 (temp)
- varias rotacoes fixas (1k, 2k, 3k) -> trava escala do byte 6/15 (RPM)
- P x D, acelerando em movimento -> razao real (bytes 44-54)
Nao gravar em CVT_DIDS como confirmado ate ter 2+ contrastes batendo.
