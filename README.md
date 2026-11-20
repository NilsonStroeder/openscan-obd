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

## Instalação

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

Se o PowerShell recusar o `Activate.ps1`, chame direto
`.\.venv\Scripts\python.exe -m openscan_obd.cli --help`.

Drivers J2534 como o do GODIAG costumam ter DLL de **32 bits** (`GODIAG_PT32.dll`):
use Python de 32 bits para o modo hardware. O modo mock não precisa de nada disso.

## Uso rápido

```powershell
# perfis disponíveis e o quanto cada um foi validado
python -m openscan_obd.cli profiles

# dashboard offline (mock, sem carro) em http://127.0.0.1:8000
python -m openscan_obd.cli dashboard

# dashboard com o carro (padrão: perfil genérico, só OBD-II)
python -m openscan_obd.cli dashboard --hardware --dll "C:\caminho\driver.dll"

# com um perfil específico
python -m openscan_obd.cli dashboard --hardware --dll "C:\caminho\driver.dll" `
  --profile nissan-sentra-b16-2010

# conferir o adaptador sem carro
python -m openscan_obd.cli j2534-check --dll "C:\caminho\driver.dll"
```

Por padrão o dashboard escuta só em `127.0.0.1`. Use `--host 0.0.0.0` apenas em rede confiável.

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

```powershell
python -m pytest tests --ignore=tests/browser      # offline, sem carro
python -m pip install -e . -r requirements-browser.txt
python -m playwright install chromium
python -m unittest discover -s tests/browser -v     # navegador (Python 64 bits)
```

## Limitações conhecidas

- ABS, airbag e A/C do Sentra de teste não responderam em 0x700–0x7FF.
- DTCs do câmbio/ECM (`17 FF 00`) decodificados, mas bytes de status e significado não validados.
- Fórmulas do câmbio (ATF, lock-up) são estimativas; teste em movimento ainda pendente.
- ELM327 nunca foi testado com hardware real.
- `scan-22` ainda não foi rodado no carro.

## Aviso

Projeto independente, sem vínculo com a Nissan Motor Co. ou GODIAG. Nissan, Sentra e
GODIAG são marcas de seus respectivos donos, citadas só para identificar o veículo e o
adaptador testados.

## Licença

[MIT](LICENSE) © 2026 Nilson Stroeder Filho
