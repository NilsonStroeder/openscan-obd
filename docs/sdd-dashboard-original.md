SDD - NissanScan CVT Dashboard
24 de out. de 2026 · Nilson Stroeder Filho
Sistema de diagnóstico e monitoramento Nissan com dashboard web e gateway J2534/KWP2000.

**Estado desta revisão (2026-10-25):** o repositório usa dados de campo do
Sentra B16 2010 (JF011E/RE0F10A). O B17 (MR20DE/RE0F10H) permanece o veículo
descrito pelo projeto de dashboard, mas ainda sem validação no veículo.
Não assumir que endereços, LIDs, bytes ou fórmulas do B16 se aplicam ao B17.

## Ambiente de referência do gateway

- DLL: `C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll`
  (32 bits; requer Python 32-bit).
- Adaptador serial indicado: `COM9`; não é usado pelo gateway J2534 atual.
- Gateway KWP novo: wrapper próprio via `ctypes` (`gateway/j2534.py`).
- Código legado OBD-II/UDS: `udsoncan.connections.J2534Connection`.
- ECM do veículo de teste B16: TX/RX `0x7E0` / `0x7E8`.
- Sessão `0xC0` está implementada e usada pelo mock; não foi confirmada
  comunicando com o ECM real.
1. Visao Geral
1. Visao Geral
O NissanScan é um sistema de diagnóstico automotivo com gateway Python e interface web. O MVP atual oferece dashboard e stream WebSocket, integrados ao poller KWP, com mock offline por padrão. Leitura com hardware é opt-in e ainda não validada no veículo; parâmetros CVT e DTCs não são apresentados como dados disponíveis.
Escopo V1:
• Dashboard Geral/CVT e stream com indicação de origem, conexão e payload cru
• Backend Python com API REST + WebSocket integrado ao poller
• Frontend HTML/JS responsivo no navegador
• Modo de desenvolvimento mock usando fixture registrada
Fora do escopo V1: app Android, calibracao de odometro, captura de LOCKUP em rodovia, suporte a outros veiculos.
2. Arquitetura
2. Arquitetura
Quatro camadas em sequencia, cada uma com responsabilidade isolada:
Camada
Tecnologia
Funcao
Hardware
GODIAG GD101 (J2534)
Interface CAN/KWP com o carro
Gateway
Python 3 + ctypes J2534 wrapper
Abre sessão KWP, lê LIDs crus e faz polling em thread separada
API
FastAPI + WebSocket
Expõe estado/cache e streaming do poller; sem chamadas de hardware em endpoints
Frontend V1
HTML + JS
Dashboard web, sem framework
App (futuro)
Kotlin (Android)
App nativo substituindo o frontend
Restrições de plataforma: a DLL GODIAG_PT32.dll é 32-bit e requer Python 32-bit. O servidor usa localhost por padrão; para hardware, o processo roda no PC com a DLL/adaptador.
Fluxo de dados: J2534 -> KWPSession 0xC0 -> leitor KWP 0x21 -> poller thread (100ms, keep-alive 2s) -> asyncio.Queue -> API/WebSocket -> browser.
O servidor ASGI precisa de uma implementação WebSocket instalada para servir
`/ws/live`; a dependência `websockets>=12.0` está declarada tanto em
`pyproject.toml` como em `requirements.txt`. Sem ela, a página HTTP pode abrir,
mas o upgrade WebSocket falha e o dashboard não recebe frames.
3. Dados Disponiveis
3. Dados Disponiveis
Parâmetros propostos pelo SDD para o ECM, ainda não confirmados por medição
cruzada. O decoder rejeita payloads menores que 13 bytes e retorna
`verified: false`; nenhuma fórmula deve ser apresentada como valor validado.
ECM — 0x7E0 (motor e CVT)
Parametro
LID
Bytes
Formula
Tela
RPM
0x01
b[0:1] BE
x * 12.5
CVT + Geral
VSP (km/h)
0x01
b[2:3] BE
x / 100
CVT + Geral
TPS (%)
0x01
b[4]
x * 100/255
Geral
ECT (C)
0x01
b[5]
x - 40
Geral
IAT (C)
0x01
b[6]
x - 40
Geral
INJPW (ms)
0x01
b[7:8] BE
x * 0.01
Geral
IGNADV (deg)
0x01
b[9]
(x - 128) * 0.5
Geral
O2S1 (V)
0x01
b[10]
x * 4.96/255
Geral
STFT (%)
0x01
b[11]
(x - 128) * 100/128
Geral
LTFT (%)
0x01
b[12]
(x - 128) * 100/128
Geral
MAP (kPa)
0x21
confirmar
confirmar
Geral
CVT_LINE_P
0x21
confirmar
confirmar
CVT
CVT_RATIO
0x21
confirmar
confirmar
CVT
ATF_TEMP
0x21
confirmar
confirmar
CVT
LOCKUP
0x21
confirmar
bit flag
CVT
BCM — 0x745
Parametro
LID
Tela
Identificacao
0x01
Info
Status luzes/portas
0x1F, 0x20, 0x21
Geral
Dados extras
0x32, 0x40, 0x60
a classificar
IPDM — 0x74D
Parametro
LID
Tela
Identificacao
0x01
Info
Tensao bateria (hipotese)
0x10
Geral
EPS — 0x742
Parametro
LID
Tela
Identificacao
0x01
Info
Angulo direcao
0x20
Geral
VSP via EPS (confirmar)
0x40, 0x60
Geral
METER — 0x743
Parametro
LID
Tela
Dados painel 1
0x12
a classificar
Dados painel 2
0x13
a classificar
Dados extras
0x20, 0x40, 0x60
a classificar
4. Telas da V1
4. Telas da V1
Tres telas navegaveis por tabs no browser. Todas recebem dados via WebSocket do backend.
Tela 1: Dashboard CVT
Foco no CVT RE0F10H como objetivo futuro. Os campos ratio, pressão, ATF e
lock-up ficam "não validados/indisponíveis"; nenhum LID de CVT é lido pelo
poller atual.
Tela 2: Dashboard Geral
Mostra valores do decoder quando o LID 0x01 contém pelo menos 13 bytes. A
origem, payload hex e estado de conexão são mostrados; fórmulas permanecem
experimentais e `verified: false`. A grade inclui RPM, VSP, TPS, ECT, IAT,
INJPW, avanço, O2S1, STFT e LTFT. Cada campo é rotulado como hipótese; origem,
timestamp e payload cru acompanham o frame.
Tela 3: DTC Scan
Informativa; a API e o dashboard não iniciam leituras DTC. Há um comando CLI
KWP 0x18 isolado que preserva a resposta crua, ainda não validado no veículo.
Limpeza de DTC não implementada.
5. Backend - API
5. Backend - API
FastAPI servida no mesmo PC. O comando inicia em modo mock por padrão; o modo
hardware requer `--hardware`. Endpoints leem apenas o cache, não chamam a DLL.
Endpoints REST
Endpoint
Metodo
Descricao
/api/status
GET
Modo mock/J2534, origem e estado da sessão
/api/modules
GET
ECM configurado; não representa descoberta do veículo
/api/dtcs
GET
Estado: leitura não executada/não implementada
/api/params
GET
Último frame de polling em cache
WebSocket
ws://127.0.0.1:8000/ws/live — envia JSON a cada novo frame:
{
  "ts": 1729800000.123,
  "conn": true,
  "data_source": "recorded_fixture",
  "lid_available": true,
  "raw_lid01": "001b0000",
  "verified": false
}
`raw_lid01` pode ser nulo quando a leitura não foi positiva. Payload curto
pode ser preservado, mas o decoder só roda a partir de 13 bytes. Valores do
decoder carregam `profile: sdd_b17_ecm_lid01` e `verified: false`. O gateway
executa I/O bloqueante na thread `KWPPoller` e publica no event loop via
`asyncio.Queue`; o endpoint WebSocket transmite os novos frames.
6. DTCs - Leitura e Exibicao
6. DTCs - Leitura e Exibicao
O dashboard e a API não executam leitura ou limpeza de DTC. Existe um comando
CLI isolado `read-kwp-dtcs` que abre a sua própria conexão J2534 e envia uma
única requisição KWP `0x18` após receber IDs, subtipo de sessão e status mask
explicitamente. A resposta fica crua em hex; nenhum DTC é decodificado.
Esta implementação não foi validada no veículo. Parar o dashboard antes de
usar, pois o adaptador/driver pode não suportar conexões simultâneas.
Não implementar nem enviar KWP `0x14` (limpeza). A tabela de endereços antiga
era uma proposta, não uma lista de módulos descobertos ou validados.
7. Limitacoes Conhecidas
7. Limitacoes Conhecidas
Parametro
Status
Motivo
MAF (g/s)
Indisponivel
MR20DE usa MAP + Speed Density. Sem sensor MAF fisico instalado.
MAP (kPa)
Nao confirmado via KWP
ECU usa MAP internamente, mas nao serializa pelo LID publico testado. Pode existir em LID 0x21 (a confirmar).
Knock (contagem)
Indisponivel
Processado em hardware ASIC dedicado. Nunca exposto diagnosticamente em KWP.
ABS DTCs
Indisponivel
ABS esta no B-CAN. OBD-II port conecta apenas ao C-CAN.
Airbag DTCs
Indisponivel
Mesmo motivo: B-CAN only.
HVAC data
Indisponivel
Mesmo motivo: B-CAN only.
Odometro
Nao confirmado
METER LIDs 0x12/0x13 nao contem 172950 km nos bytes testados. LIDs 0x61-0xFF ainda nao varridos.
LOCKUP em rodovia
Nao capturado
Requer velocidade acima de 80 km/h em pista. Confirmar na proxima saida.
Tensao bateria
Hipotese
IPDM LID 0x10 b[2]=0xF4, formula ÷16 resulta em ~15.3V. Precisa calibracao com multimetro.
UDS
Recusado
Todos os 7 modulos respondem NRC 0x12 (subFunctionNotSupported) para DiagnosticSessionControl 0x01. KWP-only.
8. Roadmap
8. Roadmap
V1 (atual — este documento)
[x] Mock J2534 com fixture registrada para testes offline
[x] Wrapper J2534 ctypes com timeout e tratamento de buffer vazio
[x] Sessão KWP `0xC0` com TesterPresent
[x] Leitor de LID `0x21` com mínimo conhecido e modo de preservação de payload curto
[x] Decoder puro ECM LID 0x01 com mínimo de 13 bytes e `verified: false`
[x] Poller KWP em thread publicando frames para asyncio
[x] API REST/WebSocket ligada ao poller, mock por padrão
[x] Interface web inicial com abas Geral/CVT/DTC e exibição de payload cru
[x] Testar decoder com payload sintético >=13 bytes; validar `verified: false`
[x] Testar API/WebSocket com fixture curta, incluindo dois clientes em paralelo
[x] Testar integração API end-to-end com payload de 13 bytes e decodificação não validada
[x] Expor os 10 campos de motor propostos no dashboard Geral
[x] Testar recuperação do poller após timeout transitório de sessão
[x] Cobrir estrutura das abas e estados de falha/recuperação do dashboard offline
[ ] Validar sessão/endereços e parâmetros no veículo antes de tratar dados como reais
[x] Implementar comando CLI isolado KWP 0x18, somente leitura e resposta crua;
    validação de veículo/protocolo ainda pendente
[ ] Clear DTCs fora do MVP; exige aprovação e revisão de segurança separada
V2 — Dados Pendentes
[ ] Varrer METER LIDs 0x61-0xFF para localizar odometro (172950 km)
[ ] Capturar LOCKUP ON em rodovia (acima de 80 km/h)
[ ] Confirmar MAP via ECM LID 0x21 com medicao correlata
[ ] Confirmar VSP via EPS LID 0x40/0x60 (b[9] hipotese)
[ ] Investigar ATF_TEMP anomalia (leitura de 22 C com motor quente)
V2 — Visualização de logs (relatório offline inicial)
[x] Exportar capturas JSONL para série temporal CSV e adicionar visualização
    de gráficos navegáveis com eixo de tempo e seleção de sinais, incluindo
    RPM, avanço de ignição, O2S1, VSP, TPS, temperaturas e trims quando
    disponíveis no frame.
[x] Exibir origem, perfil, unidade e estado `verified` junto dos sinais;
    identificar O2S1 como tensão hipotética, não como AFR/lambda validada.
[x] Representar frames ausentes/desconectados como lacunas, sem interpolar
    valores crus ou ligar visualmente períodos sem comunicação.
[x] Manter a visualização estritamente somente leitura; sem edição de mapa,
    tuning, escrita ou rotinas ECU. Referências visuais do usuário servem
    apenas como inspiração para gráficos/gauges 2D, não para reprodução da UI.
Relatório inicial disponível nos comandos `plot-capture` (HTML offline) e
`export-capture-csv`. Gráficos só incluem sinais decodificados já presentes
na captura; permanece necessário validar no veículo as fórmulas e unidades.
[x] Versionar capturas como schema JSONL 1 e rejeitar versões ausentes,
    inválidas ou não suportadas antes de analisar e visualizar.
[x] Comparar duas capturas em HTML offline por tempo decorrido, expondo
    divergências de veículo/ECU/perfil/decoder/`verified` sem alegar que as
    condições de condução ou medições são equivalentes.
V3 — App Android
[ ] Separar gateway Python em servico Windows (startup automatico)
[ ] Desenvolver app Kotlin (Android) consumindo a mesma API FastAPI
[ ] Substituir frontend web pelo app como interface principal
[ ] Notificacoes push para DTCs e temperatura CVT critica
Criterio de encerramento da V1: testes offline completos; depois, validar sessão e
polling no veículo por 30 minutos antes de habilitar dados reais no dashboard.
DTC scan não faz parte do critério atual.
9. Revisao Critica e Tarefas Atomicas
9.1 Escopo e veículo alvo
B16/JF011E/RE0F10A é o veículo que originou as capturas existentes. O SDD
mantém B17/RE0F10H como alvo proposto, sem evidência de campo no momento.
Não transferir LIDs, endereços ou fórmulas entre plataformas sem validação.

9.2 Arquitetura implementada e limites
- Todo I/O J2534 ocorre na thread do `KWPPoller`, nunca em uma coroutine.
- A thread publica snapshots completos na `asyncio.Queue`; o event loop atualiza
  a referência do último frame e notifica clientes WebSocket.
- O poller tenta sessão `0xC0`, envia `TesterPresent` a cada 2 s e publica
  estado de conexão/erro; falhas de transporte/sessão recebem backoff
  exponencial de 1 a 5 s. Implementação testada apenas com mock.
- LID 0x01 exige 13 bytes para decodificação. Payload positivo curto pode ser
  preservado em hex, sem atribuição de significado.
- O decoder implementa fórmulas do SDD como hipótese e sempre retorna
  `verified: false`; não confirma que o ECM as use.
- WebSocket transmite atualizações independentes para cada cliente conectado;
  o navegador tenta reconectar após desconexão com espera exponencial limitada
  a 30 s, reiniciada depois que chega um frame.
- O dashboard diferencia conexão KWP indisponível, LID sem resposta, erro de
  decodificação e WebSocket desconectado; campos decodificados são limpos
  quando conexão/LID não permitem uma leitura atual. A interface não mantém
  valores anteriores como se fossem atuais.
- Não há leitura DTC na API/poller nem operações de escrita, reset ou rotina
  ativa. A única exceção é o comando CLI standalone KWP 0x18, raw-only e ainda
  não validado no veículo.

9.3 Tarefas concluídas conforme commits de 2026-10-25
- T1.0 Mock J2534 + fixture gravada: concluído (`40e70a9`).
- T1.1 Wrapper J2534 `ctypes`: concluído (`ac6ab5b`).
- T1.2 Sessão KWP e keep-alive: concluído como implementação; não validado no
  veículo (`efb67ec`).
- T1.3 Leitor KWP LID: concluído (`edd903d`); mínimo padrão 13 bytes para ECM
  LID 0x01, com opção explícita de preservar resposta curta.
- T1.4 Decoder ECM LID 0x01: concluído com testes sintéticos offline
  (`5083cd1`); fórmulas não confirmadas em campo.
- T1.5 Poller em thread e fila: concluído (`93693eb`).
- T2.1 a T2.3 API, REST cache e WebSocket: concluídos nesta integração;
  ciclo de vida e fan-out por condição asyncio em `api/main.py`.
- Testes offline da API: recuperação após timeout transitório de leitura KWP
  e entrega independente do WebSocket para dois clientes (`tests/test_api_main.py`).
- T3.1 Interface mínima: abas Geral/CVT/DTC, payload cru e reconexão automática
  concluídos em `static/dashboard.html`.
- UX do dashboard: estados distintos para falha KWP, ausência de resposta LID
  e desconexão WebSocket; reconexão progressiva limitada a 30 s, com dados
  decodificados limpos quando indisponíveis.
- Captura de campo opcional em JSONL via `dashboard --capture`: registra
  metadados do veículo/ECU/adaptador, frames, timestamps, erros e payload cru;
  não sobrescreve arquivos existentes e marca dados como não validados.
- Análise offline de captura via `analyze-capture`: resume duração, falhas e
  recuperações e durações de interrupção, intervalos p50/p95/máximo entre
  frames (base `frame.ts`, nearest-rank), maior lacuna, disponibilidade do LID
  e variações dos payloads crus; não interpreta bytes nem altera o arquivo.
- Leitura KWP DTC 0x18 em `read-kwp-dtcs`: comando standalone, IDs/sessão/máscara
  explícitos, conexão separada e resposta crua; não integrado à API/poller e
  ainda sem validação no veículo.
- API/dashboard não iniciam leitura DTC. Limpeza KWP 0x14 e ações DTC continuam
  fora do escopo; exigem aprovação e revisão de segurança separada.

9.3.1 Captura JSONL e análise offline
- `dashboard --capture <arquivo.jsonl>` é opt-in e cria um arquivo novo, sem
  sobrescrever capturas existentes. Funciona em mock ou hardware explicitamente
  selecionado; não habilita hardware por si só.
- O arquivo registra eventos `capture_started`, `frame` e `capture_stopped`.
  O início contém `schema_version: 1` e metadados informados para
  veículo/ECU/adaptador, perfil configurado, protocolo, IDs TX/RX, origem,
  caminho da DLL quando aplicável e `validation_status: not_validated`. Cada
  frame preserva `captured_at`, o
  timestamp Unix do poller (`frame.ts`), estado da conexão/LID, erros,
  payload hex cru e, quando presentes, campos do decoder. A captura não
  transforma a hipótese do decoder em dado validado.
- Se a gravação falhar durante a execução, a captura é desativada e o erro fica
  exposto em `/api/status` (`capture_error`); os frames continuam disponíveis
  ao dashboard, sem fingir que foram gravados com sucesso. O encerramento normal
  tenta registrar `capture_stopped`; sua ausência identifica captura incompleta.
- `analyze-capture <arquivo.jsonl>` valida a estrutura e resume duração,
  completude, contagem de frames conectados/desconectados, falhas/recuperações,
  períodos sem resposta do LID, payloads crus distintos e mudanças consecutivas.
  `--json` emite o resumo estruturado. JSONL inválido, evento fora de ordem,
  evento que não seja string conhecida, timestamp sem fuso, `frame.ts` não
  finito/fora de ordem, `verified` fora de boolean/null, perfil/origem/erros
  fora de string/null ou demais campos estruturais inválidos produzem erro
  explícito.
- A versão do schema é obrigatória no registro inicial, deve ser inteiro (não
  booleano) e atualmente precisa ser exatamente `1`. Versão ausente, formato
  inválido ou versão desconhecida é rejeitada; não há inferência silenciosa de
  versão antiga nem migração automática. Uma futura alteração incompatível deve
  incrementar a versão e documentar migração/compatibilidade antes de ser aceita.
- As durações de interrupção usam o timestamp do primeiro frame sem conexão e
  o primeiro frame posterior reconectado; interrupção ainda aberta é marcada
  como `ongoing` e observada até o fim da captura. Intervalos p50/p95/máximo e
  maior lacuna usam `frame.ts` (timestamp Unix do poller); percentis usam
  nearest-rank. Uma lacuna longa é uma observação temporal, não prova isolada
  de falha do veículo nem um indicador automático de qualidade.
- A análise é estrutural: não decodifica payloads crus, não atribui unidades e
  não altera a captura de origem. O relógio `captured_at` e `frame.ts` têm
  funções distintas; estatísticas entre frames usam `frame.ts`.

9.3.2 Exportação CSV e relatório de gráficos
- `export-capture-csv <captura.jsonl> --out <arquivo.csv>` gera uma linha por
  frame com timestamps UTC, segundos desde o início, metadados de veículo/ECU/
  adaptador/perfil, origem, estados de conexão e LID, payload cru, perfil e
  `verified`, valores numéricos disponíveis, erro e erro de decodificação.
  Campos ausentes ficam vazios; o payload original continua disponível em hex.
- Textos externos exportados para CSV recebem prefixo seguro quando começam
  com caracteres que podem iniciar fórmula de planilha (`=`, `+`, `-`, `@`,
  tab ou carriage return). A exportação não reescreve nem remove dados do JSONL.
- `plot-capture <captura.jsonl> --out <relatorio.html>` cria um relatório HTML
  autossuficiente, para abrir localmente, com gráficos SVG 2D selecionáveis
  para RPM, VSP, TPS, ECT, IAT, pulso de injeção, avanço, O2S1, STFT e LTFT
  quando existirem valores numéricos finitos. Eixo X é tempo desde a primeira
  amostra; cada gráfico apresenta unidade, tooltip por amostra e intervalo de
  valores observado, junto dos metadados, estado de completude, falhas/
  recuperações, maior interrupção, p50/p95, maior lacuna, perfis, estados
  `verified` e payloads crus observados.
- O relatório HTML não usa CDN, bibliotecas remotas nem requisições de rede.
  Metadados são inseridos como texto, e os dados JSON embutidos escapam
  caracteres capazes de encerrar o elemento `script`. HTML e CSV são criados
  em modo exclusivo; se a saída já existir, o comando falha em vez de
  sobrescrevê-la.
- Os gráficos só usam campos numéricos decodificados já presentes no frame;
  não tentam decodificar payloads crus. Frames desconectados, LID ausente,
  valor ausente ou intervalo maior que o limiar visual encerram um segmento,
  sem interpolação. O limiar é uma heurística visual derivada do intervalo
  mediano observado, com piso de 1 s e fator 3; não classifica estabilidade
  mecânica ou qualidade da comunicação.
- Todos os rótulos/unidades do decoder permanecem hipóteses. O2S1 é apresentado
  como tensão hipotética, nunca como AFR/lambda confirmado. O relatório não é
  uma interface de tuning: é somente leitura e não envia comandos ao veículo.
- Ambos os comandos validam timestamps, ordem dos frames, estados booleanos e
  valores numéricos finitos antes de gerar arquivos; erro de entrada não deve
  resultar em relatório aparentemente válido.
- `compare-captures <captura-a.jsonl> <captura-b.jsonl> --out <comparacao.html>`
  gera um relatório HTML autossuficiente sobrepondo os sinais numéricos comuns
  às duas capturas, com seleção de sinal, SVG, legendas por arquivo, tooltip por
  ponto e metadados de cada coleta. O comando aplica a mesma validação de schema,
  timestamp, ordem, conexão, disponibilidade do LID e finitude numérica usada
  pela exportação/visualização individual.
- O eixo horizontal da comparação é tempo decorrido desde o primeiro frame de
  cada captura, independente para cada série; não há alinhamento pelo relógio,
  sincronização de eventos, ajuste de atraso, reamostragem ou interpolação. As
  lacunas quebram os segmentos individualmente. Só sinais com valores
  numéricos válidos nas duas capturas aparecem como comparáveis; se não houver
  nenhum, o relatório informa explicitamente que não há sinais comuns.
- O relatório sinaliza diferenças em metadados disponíveis (veículo, ECU,
  perfil do veículo, adaptador e estado de validação), bem como diferenças nos
  perfis do decoder e estados `verified` observados nos frames. Metadados iguais
  não comprovam equivalência de ECU, decoder, sessão, firmware, condições
  ambientais ou estado de condução. O usuário deve confirmar essas condições
  antes de interpretar sobreposição. Valores decodificados seguem como
  hipóteses e O2S1 continua sendo tensão hipotética, não AFR/lambda confirmada.
- A saída HTML é criada em modo exclusivo e nunca substitui arquivo existente.
  A comparação não edita as capturas, não decodifica payloads crus e não envia
  comandos ao carro.

9.3.3 Testes e validação offline
- Testes automatizados cobrem exportação CSV, preservação de payload/estado
  `verified`, gráficos disponíveis e lacunas, escaping de metadados não
  confiáveis, recusa a sobrescrever saída e integração dos comandos CLI.
- Testes de schema cobrem versão ausente, versão não suportada e booleano
  (embora Python trate `bool` como subtipo de `int`), metadados obrigatórios e
  timestamps de frame fora de ordem, nomes de evento malformados e tipos
  inválidos de perfil/`verified`; capturas válidas passam pelo schema
  versionado antes de qualquer resumo ou relatório.
- Testes de comparação cobrem sobreposição de sinal comum, alinhamento por
  tempo decorrido, metadados divergentes, ausência de sinal comum e integração
  do comando CLI.
- Testes do dashboard verificam que abas e painéis correspondem, que Geral é a
  tela inicial e que as mensagens cobrem falha KWP, LID sem resposta, erro de
  decodificação e valores experimentais. O teste de recuperação do poller
  confere a sequência frame válido -> timeout sem valores antigos -> frame
  recuperado com payload preservado.
- A dependência WebSocket foi exercitada no servidor Uvicorn local: sem uma
  implementação WebSocket instalada, o HTML servia, mas `/ws/live` falhava
  com 404. `websockets>=12.0` foi então adicionada aos manifests de dependência;
  após a instalação, foram conferidos handshake, stream do mock e navegação
  entre as abas no navegador.
- A suíte automatizada de browser usa Chromium/Playwright e um dashboard
  iniciado em processo local com `--mock`; nenhum teste abre hardware ou
  depende de serviço externo. Cobre stream real do mock, navegação entre abas,
  estado de erro e recuperação WebSocket simulados, aviso de diferenças na
  comparação, seleção/ocultação do gráfico e estado sem sinais comuns.
- A suíte de browser é opcional para o desenvolvimento normal: instalar com
  `python -m pip install -e . -r requirements-browser.txt`, instalar o browser
  com `python -m playwright install chromium` e executar
  `python -m unittest discover -s tests/browser -v`. A suíte unitária padrão
  permanece `python -m unittest discover -s tests -v`.
- GitHub Actions executa testes unitários e browser em push e pull request;
  o job instala Chromium com as dependências do sistema. Esses testes validam
  a interface e o comportamento com mock, não a comunicação ou compatibilidade
  com veículo/adaptador real.
- Validação local desta revisão: 145 testes unitários e 4 testes browser
  passaram; `git diff --check` passou. No Windows, Playwright requer ambiente
  Python 64 bits, separado do ambiente 32 bits que pode ser necessário para
  alguns drivers J2534. O workflow de CI foi configurado, mas não executado
  neste ambiente local.

9.4 Próximos passos sem veículo
1. [x] Acrescentar testes de falha e recuperação do poller/API sem equipamento.
2. [x] Melhorar UX de sessão/LID indisponível e reconexão do WebSocket.
3. [x] Preparar captura rastreável de frames e erros para validação futura.
4. [x] Implementar resumo offline das capturas JSONL, sem inferir significado
   para os payloads crus, incluindo durações de interrupção e estatísticas de
   intervalo entre frames.
5. [x] Adicionar leitura KWP DTC crua como comando separado do dashboard;
   verificar serviço/máscara/resposta no veículo antes de interpretar dados.
6. [x] Exportar capturas para CSV e gerar gráficos HTML/SVG offline, somente
   leitura, sem interpolar falhas ou interpretar bytes crus.
7. [x] Cobrir estrutura das abas, estados da interface e transição de falha/
   recuperação nos testes offline do dashboard.
8. [x] Declarar e validar dependência de servidor WebSocket no Uvicorn;
   confirmar handshake e dashboard navegável usando mock local.
9. [x] Versionar o schema JSONL e rejeitar arquivos sem versão ou com versão
   desconhecida antes de analisar/exportar.
10. [x] Comparar duas capturas offline em relatório HTML, alinhadas pelo tempo
    decorrido de cada captura e sem afirmar equivalência de condições.
11. Validar sessão e polling no veículo por 30 minutos; registrar veículo,
    ECU, adaptador/driver e respostas cruas antes de interpretar qualquer
    parâmetro. Este passo depende de acesso ao veículo.
12. Manter mock como padrão. `--hardware` continua explícito e não significa
   compatibilidade confirmada.
13. [x] Adicionar suíte persistente de interação browser/CI com Chromium e
    Playwright. Os cenários cobrem navegação por abas, stream do mock,
    apresentação de falha/recuperação WebSocket, aviso de metadados divergentes,
    visibilidade do gráfico e estado sem sinal comum. O workflow roda em push e
    pull request; instalação e comando local estão documentados no README.

9.5 Dependências de validação futura
- Confirmar que `10 C0` é aceito no endereço e veículo escolhidos.
- Registrar veículo, ECU, adaptador/driver e payload cru ao validar cada
  parâmetro; manter escala/unidade como hipótese até haver correlação.
- Só então avaliar habilitar dados reais com perfil de veículo selecionado.
- Validar no veículo a sessão/endereço/status mask do comando KWP DTC; manter a
  resposta crua até identificar formato e aplicação.
- Não implementar limpeza de DTCs sem aprovação explícita e revisão separada.
