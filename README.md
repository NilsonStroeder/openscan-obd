# openscan-obd

Scanner de diagnóstico automotivo **somente leitura**, em Python: OBD-II padrão,
KWP2000/UDS sobre CAN e adaptadores J2534, com um dashboard web em tempo real.

Nasceu para ler o câmbio CVT de um Nissan Sentra B16 2010 (que não fala OBD-II
no câmbio) e virou uma base extensível: tudo que é específico de um carro mora
em **perfis de veículo**; o resto (transporte, guarda de segurança, dashboard)
é genérico.

> **Estado honesto:** validado em **um único carro** (Sentra B16 2010, adaptador
> GODIAG GD101). Muitas leituras do câmbio são hipóteses, marcadas como tais.
> Suporte a um protocolo não garante que o seu carro responda do mesmo jeito.

## O que faz

- Lê PIDs ao vivo (modo 01), DTCs (03/07/0A) e identificação (modo 09) pelo padrão SAE J1979.
- Com o perfil do Sentra B16: lê o bloco `21 01` do câmbio (RPM, velocidade, marcha, ré,
  ATF estimado, lock-up) e lê DTCs KWP (`17 FF 00`) de TCM, EPS, painel, BCM e IPDM (`ler-erros`). Os códigos conferiram com o scanner de uma oficina; o byte de status ainda não tem significado confirmado, e lista vazia **nunca** é exibida como "sem falhas".
- Dashboard web com selo de confiança por valor: `padrão`, `confirmado`, `estimado`,
  `cru`, `indisponível`. Quando não há dado, mostra o motivo.
- Varreduras de pesquisa: todos os IDs CAN (`scan-all`) e o serviço 0x22 (`scan-22`).
- Capturas JSONL com análise, gráficos HTML e CSV offline.

## Segurança

- **Só leitura.** Uma guarda (`ReadOnlyDevice`) bloqueia qualquer serviço fora de uma lista
  permitida: nada de escrita (0x2E), rotinas (0x31), SecurityAccess (0x27), reset ou
  limpeza de DTC. Não há flag para desligar isso.
- Alguns comandos abrem sessão de diagnóstico (`10 C0`); rode com o carro parado.
- Leitura de falhas do câmbio **nunca** é exibida como "sem falhas" enquanto não validada.
- Não é ferramenta de reflash. Use por sua conta e risco, no seu próprio veículo.
  Veja a licença (sem garantia).

## Primeiros passos

### O que você precisa
- **Para só experimentar:** Python 3.10 ou mais novo. Nenhum carro, nenhum adaptador.
- **Para ler um carro:** um adaptador **J2534** (testado: GODIAG GD101) com o driver instalado, e o carro
  com a ignição ligada. Drivers como o do GODIAG usam DLL de **32 bits** (`GODIAG_PT32.dll`), então use
  Python de **32 bits** no modo hardware. ELM327 também é aceito, mas nunca foi testado em carro real.

### 1. Experimente sem carro (modo simulado)
No Windows (PowerShell), na pasta do projeto:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m openscan_obd.cli dashboard
```

Abra http://127.0.0.1:8000. Você verá o dashboard com dados gravados de exemplo.
(Se o PowerShell recusar `Activate.ps1`, não ative o ambiente: chame o `python.exe` do `.venv` direto, como acima.)

### 2. Com o carro (Windows, atalhos de dois cliques)
Todos os `.bat` criam o ambiente Python (`.venv`) sozinhos na primeira vez. Se o seu driver não for o do
GODIAG, edite o caminho da DLL no `.bat` (ou passe `--dll "C:\caminho\driver.dll"` nos comandos abaixo).
Carro **parado**, ignição ligada ou motor em P com freio de mão.

| Quero… | Dê dois cliques em |
|---|---|
| Ver o dashboard ao vivo (grava uma captura em `logs/`) | `dashboard_carro.bat` |
| Ler os códigos de falha de todos os módulos (não apaga nada) | `ler_erros.bat` |
| Testar se o adaptador está funcionando | `testar_adaptador.bat` |
| Coletar dados em campo, passo a passo, com instruções na tela | `roteiro_guiado.bat` e `roteiro_guiado_andando.bat` |
| Gerar um relatório das capturas que você fez | `analisar_log.bat` |

Os outros `roteiro_*.bat` são etapas de pesquisa avançada; comece pelos de cima.
Os arquivos gerados ficam em `logs/`, que o git ignora porque pode conter o VIN do seu carro.

### 3. Linha de comando (Linux, macOS ou se preferir)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python -m openscan_obd.cli profiles                      # perfis e o quanto cada um foi validado
python -m openscan_obd.cli dashboard                     # simulado
python -m openscan_obd.cli dashboard --hardware --dll /caminho/driver.dll --profile nissan-sentra-b16-2010
python -m openscan_obd.cli ler-erros --dll /caminho/driver.dll
python -m openscan_obd.cli j2534-check --dll /caminho/driver.dll   # conferir o adaptador sem carro
```

Sem `--profile`, o dashboard usa o perfil genérico (só OBD-II padrão, funciona em qualquer carro que fale
SAE J1979). Por padrão ele escuta só em `127.0.0.1`; use `--host 0.0.0.0` apenas em rede confiável.

### Problemas comuns
- **"Nao consegui criar o ambiente"**: instale o Python 3.10+ (32 bits) em python.org, marque *Add to PATH*.
- **Dashboard abre mas sem dados / "KWP indisponível"**: confira o caminho da DLL, se o Python é de 32 bits
  e se **nenhum outro programa** está usando o adaptador (feche outros dashboards e softwares do fabricante).
- **Adaptador travou depois de uma varredura**: tire e ponha o cabo USB. Nunca varra os IDs 0x600–0x6FF.
- **Um valor aparece como "indisponível"**: o módulo não fornece aquele dado neste carro. Isso é esperado, não é erro.
- **Selos nos valores**: `padrão` (OBD-II SAE J1979), `confirmado` (validado no carro de teste),
  `estimado` (sem referência independente), `cru` (byte sem interpretação), `indisponível`.

### Comandos de pesquisa (carro parado, ignição ligada)

| Comando | Para quê |
|---|---|
| `scan` | Enumera módulos do perfil e lê DTCs/VIN/dados ao vivo |
| `discover` | Procura módulos que respondem em 0x700–0x7FF |
| `scan-all` | Varredura longa de IDs CAN (`--start 700 --end 7FF`). **Não varra 0x600–0x6FF**: trava o GD101 |
| `scan-22` | Varre DIDs do serviço 0x22 num par de IDs |
| `scan-dids` | Varredura simples de DIDs UDS |
| `probe-dtc` | Hipóteses de leitura de DTC do câmbio |
| `probe-kwp`, `snapshot`, `compare` | Pesquisa KWP `21 <LID>` |
| `read-kwp-dtcs` | Uma leitura KWP `18` isolada |
| `analyze-capture`, `plot-capture`, `export-capture-csv`, `compare-captures` | Análise offline de capturas |
| `elm-check`, `dashboard --elm PORTA` | Transporte ELM327 (só testado com adaptador falso) |

Use `--help` em cada um. Relatórios vão para `logs/` (ignorado pelo git: pode conter VIN).
Exemplos reais já limpos estão em [`docs/exemplos/`](docs/exemplos/).

## Estrutura

```
src/openscan_obd/
├── profiles/     # um arquivo por veículo (endereços, módulos, o que é validado)
├── gateway/      # J2534 (ctypes), ELM327, KWP, poller, scans, decoders, mock offline
├── api/          # FastAPI + WebSocket
├── static/       # dashboard
├── obd2.py kwp.py did_scan.py dids.py ...
└── cli.py
tests/            # sem hardware; tests/browser usa Playwright (opcional)
docs/             # notas de protocolo, SDDs, exemplos
experimental/     # abordagens arquivadas
```

## Expandir para outros carros

Basta criar um perfil. Veja [`docs/adicionar-veiculo.md`](docs/adicionar-veiculo.md)
e o [`CONTRIBUTING.md`](CONTRIBUTING.md). Contribuições de logs sanitizados de outros
carros são muito bem-vindas, inclusive as que mostram que algo **não** funciona.

## Testes

```bash
pip install -e . pytest
python -m pytest tests --ignore=tests/browser          # offline, sem carro (a suíte principal)
```

Os testes de tela (`tests/browser`) usam um navegador real e são opcionais:

```bash
pip install -r requirements-browser.txt                # instala o Playwright
python -m playwright install chromium                  # baixa o navegador na versão certa
python -m pytest tests/browser
```

Sem esses dois passos os testes de navegador falham no setup; os demais não dependem deles.
A integração contínua (GitHub Actions) roda os dois grupos a cada push.

## Limitações conhecidas

- ABS, airbag e A/C do Sentra de teste não responderam em 0x700–0x7FF.
- DTCs do câmbio e demais módulos (`17 FF 00`): os códigos conferiram com o scanner de uma oficina, mas o byte de status ainda não tem significado confirmado.
- Temperatura do ATF é estimada por tabela do manual, sem referência independente; lock-up é byte cru; relação e pressão de linha não têm decodificação validada.
- ELM327 nunca foi testado com hardware real.
- `scan-22` ainda não foi rodado no carro.

## Aviso

Projeto independente, sem vínculo com a Nissan Motor Co. ou GODIAG. Nissan, Sentra e
GODIAG são marcas de seus respectivos donos, citadas só para identificar o veículo e o
adaptador testados.

## Licença

[MIT](LICENSE) © 2026 Nilson Stroeder Filho
