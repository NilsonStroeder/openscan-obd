# SDD — Transporte ELM327 (comandos AT + ISO-TP)

**Status:** implementado e testado só offline (2026-11-05). Nenhum ELM327
real foi usado. Nada aqui está validado em adaptador ou veículo.
**Código:** `src/openscan_obd/gateway/elm327.py`
**Testes:** `tests/test_elm327.py` (adaptador falso, sem serial real)

---

## 1. Objetivo

Permitir que o gateway (sessão KWP, leitor de LIDs, poller, dashboard,
`read-kwp-dtcs`) use um adaptador ELM327 no lugar do J2534, sem mudar essas
camadas. O ELM327 vira mais um "device" com a mesma interface do
`J2534Device`.

Motivação: um ELM327 Bluetooth/Wi-Fi é o caminho para, no futuro, tirar o
notebook do carro e usar o celular. Esta etapa só prepara o transporte.

## 2. Fora de escopo

- App ou página no celular (Web Bluetooth/BLE). Ver §10.
- Captura passiva (`ATMA`) — já falhou com o GD101 (`experimental/`).
- Protocolos que não sejam ISO 15765-4 CAN 11 bits 500 kbit/s (`ATSP6`).
  K-line, CAN 29 bits e 250 kbit/s ficam para depois, se aparecer módulo que
  precise.
- Qualquer serviço de escrita, rotina ou SecurityAccess. O transporte é
  neutro, mas as regras do projeto continuam valendo para quem o usa.

## 3. Interface

Igual ao `J2534Device` (`gateway/j2534.py`):

```python
dev = ELM327Device("COM5", txid=0x7E0, rxid=0x7E8)
dev.open()                       # abre a porta e roda a inicialização AT
resp = dev.send_recv(b"\x10\xc0", timeout_ms=500)   # -> b"\x50\xc0"
dev.close()
dev.data_source                  # "elm327"
dev.adapter_id                   # texto do ATI, ex.: "ELM327 v1.5"
```

- `port` aceita `COM5` (USB ou Bluetooth SPP pareado no Windows) ou URL do
  pyserial, ex. `socket://192.168.0.10:35000` (ELM Wi-Fi).
- `send_recv` devolve o payload diagnóstico completo (sem header CAN nem PCI),
  já remontado quando a resposta tem várias partes.
- Erros sobem como exceção (o poller já trata qualquer exceção como falha de
  transporte e tenta reconectar).

## 4. Inicialização (`open`)

| Comando | Por quê |
|---------|---------|
| `ATZ` | Reset. Responde com a versão; espera mais que os outros. |
| `ATE0` | Sem eco do comando. O parser também descarta eco, caso o clone ignore. |
| `ATL0` | Sem line feed extra. |
| `ATS1` | Com espaços entre bytes (o parser aceita sem espaços também). |
| `ATH1` | Mostra o header CAN de cada frame — permite conferir quem respondeu. |
| `ATCAF1` | Formatação automática ISO-TP: o ELM põe o PCI no envio e faz o controle de fluxo. |
| `ATSP6` | ISO 15765-4 CAN 11 bits 500 kbit/s (o protocolo do B16 de teste). |
| `ATSH <tx>` | Header de envio (ex. `7E0`, `7E1`, `745`). |
| `ATCRA <rx>` | Só aceita frames do ID de resposta. |
| `ATFCSH <tx>` | Header do frame de controle de fluxo. |
| `ATFCSD 300000` | Controle de fluxo: ClearToSend, sem limite de bloco, sem espera. |
| `ATFCSM1` | Usa o controle de fluxo configurado acima. |
| `ATAT1` | Timing adaptativo. |
| `ATI` | Guarda a identificação em `adapter_id`. |

**Por que configurar controle de fluxo:** sem `ATFCSH`, o ELM responde ao
primeiro frame de uma resposta longa usando um header derivado do ID de
resposta. Para 0x7E8/0x7E9 isso coincide com 0x7E0/0x7E1, mas para o BCM
(0x765) ou o módulo 0x72E não. O módulo então nunca manda o resto e a
resposta longa morre. O LID 0x01 do TCM (69 bytes) e os LIDs 0x12–0x1F
dependem disso.

**Clones:** muitos "v2.1" baratos respondem `?` a `ATFCSH`/`ATFCSD`/`ATFCSM`
ou a `ATCRA`. Qualquer `?` na inicialização vira `ELM327Unsupported`, com o
nome do comando. É o mesmo teste que o comando `elm-check` roda (§8).

## 5. Envio e leitura (`send_recv`)

1. Se o timeout pedido mudou, envia `ATST hh` (unidades de 4 ms; máx. `FF`
   ≈ 1 s). Timeouts maiores ficam no limite do ELM, e o prazo de leitura da
   serial cobre o restante.
2. Escreve os bytes em hex + `\r` (ex. `21 01`→`2101\r`).
3. Lê até o prompt `>` ou até o prazo (timeout + margem fixa).
4. Interpreta as linhas:
   - descarta linhas vazias, eco do comando e `SEARCHING...`;
   - `NO DATA` → `ELM327NoData` (subclasse de `TimeoutError`, igual a um
     timeout do J2534 para o resto do código);
   - `?` → `ELM327Error` (comando não entendido);
   - `CAN ERROR`, `BUS ERROR`, `BUS INIT...ERROR`, `UNABLE TO CONNECT`,
     `BUFFER FULL`, `STOPPED`, `<DATA ERROR`, `<RX ERROR`, `FB ERROR`,
     `LV RESET` → `ELM327Error` com o texto do adaptador;
   - demais linhas: `<header> <bytes>` (com ou sem espaços).
5. Frames de outro header são descartados (defesa extra além do `ATCRA`).
6. Remonta ISO-TP a partir do PCI de cada frame:
   - `0N` single frame, N bytes;
   - `1N NN` first frame, tamanho de 12 bits;
   - `2N` consecutive frame, sequência N (0–F, cíclica); sequência fora de
     ordem ou frame faltando → `ELM327Error`;
   - bytes de padding além do tamanho são descartados.
7. Escolhe a resposta com `classify_response` do `j2534.py`:
   positiva (`sid+0x40`) ou negativa final → devolve; frames de outro serviço
   → descarta.

### Response pending (`7F <sid> 78`)

O ELM327 para de escutar depois de devolver o prompt. Se a resposta final
chegar na mesma janela, ela já vem junto e é escolhida no passo 7. Se só vier
o `78`:

- para serviços de leitura (`0x01`, `0x03`, `0x07`, `0x09`, `0x10`, `0x18`,
  `0x1A`, `0x21`, `0x22`, `0x3E`), o pedido é reenviado com `ATST FF`, até
  `MAX_PENDING_RETRIES` vezes;
- para qualquer outro serviço, não reenvia e levanta `ELM327Error`.

Reenviar é uma aproximação: o J2534 simplesmente continua escutando. Ver
questão aberta Q2.

## 6. Mapa de erros

| Situação | Exceção | Efeito no poller/dashboard |
|----------|---------|----------------------------|
| `NO DATA` / prazo da serial | `ELM327NoData` (`TimeoutError`) | `conn=false`, reconecta |
| `?`, erro de barramento, buffer cheio | `ELM327Error` | `conn=false`, reconecta |
| Comando AT obrigatório recusado no `open` | `ELM327Unsupported` | dashboard não sobe; mensagem cita o comando |
| Resposta negativa (`7F 21 12`) | — (devolvida) | `lid_nrc` no dashboard |

## 7. Integração

- `api/main.py` `_make_device`: novo modo `elm327` além de `mock` e `j2534`.
- CLI `dashboard`: `--elm PORTA` (implica hardware; não usa `--dll`).
- CLI `elm-check --port PORTA`: roda a inicialização, mostra o `ATI`, lista
  cada comando AT aceito ou recusado e, opcionalmente (`--probe-ecm`), envia
  só `01 00` ao ECM e mostra a resposta crua. Não abre sessão KWP.
- `read-kwp-dtcs` e os outros comandos continuam só em J2534 nesta etapa.

## 8. Plano de validação quando o ELM chegar

Ordem pensada para errar cedo e sem risco (tudo leitura):

1. `elm-check --port COMx` sem o carro: deve listar todos os comandos AT
   como aceitos. Se `ATFCSH/ATFCSD/ATFCSM` falharem, o adaptador não serve
   para respostas longas fora do 0x7E8.
2. No carro, ignição ligada: `elm-check --port COMx --probe-ecm` → espera-se
   `7E8 06 41 00 ...` (bitmap de PIDs).
3. `dashboard --elm COMx --capture logs\elm_ecm.jsonl` → ECM: sessão `10 C0`
   e LID 0x01 com 4 bytes (comparar com a captura J2534 equivalente).
4. Repetir o 3 apontando para o TCM (0x7E1/0x7E9) quando o dashboard
   aceitar outro módulo, para testar a resposta de 69 bytes (multi-frame).
5. Registrar adaptador (`ATI`), firmware, conexão (USB/BT/Wi-Fi) e
   resultados em `docs/session_log_*.md`.

## 9. Testes offline

`tests/test_elm327.py` usa um adaptador ELM falso (objeto com
`write`/`read`/`close`) que responde aos comandos AT e a requests
diagnósticos com textos no formato do ELM. Cobre:

- sequência de inicialização e `adapter_id`;
- `ELM327Unsupported` quando um clone responde `?` a `ATFCSH`;
- single frame com padding, com e sem espaços;
- multi-frame (resposta de 69 bytes do TCM, a partir de payload real de
  `tests/fixtures/lid01_field_20261023.json`);
- consecutive frame fora de ordem → erro;
- `NO DATA` → `TimeoutError`; `CAN ERROR` → `ELM327Error`;
- eco e `SEARCHING...` ignorados;
- frame de outro header descartado;
- `7F 21 78` seguido da resposta final na mesma janela;
- `7F 21 78` sozinho → reenvio para leitura, erro para serviço não listado;
- `ATST` só reenviado quando o timeout muda;
- `KWPSession` + `read_lid_detailed` funcionando por cima do ELM falso.

## 10. Próxima fase: celular (não implementada)

- **Android + ELM Bluetooth clássico:** o navegador não fala SPP. Precisaria
  de app nativo ou de Python no Android (Termux), ambos fora deste repo.
- **ELM BLE + Chrome Android:** Web Bluetooth funciona com BLE; daria para
  portar o parser desta camada para JavaScript numa página estática. iPhone
  não tem Web Bluetooth no Safari.
- **ELM Wi-Fi:** página no celular não abre TCP cru; precisaria de um
  intermediário.
- **Sem ELM:** o dashboard atual já abre no celular com
  `dashboard --hardware --host 0.0.0.0` e o notebook no carro.

## 11. Questões abertas

- **Q1.** O formato exato com `ATH1 ATCAF1` em clones (PCI visível em todos
  os frames?) precisa ser conferido no adaptador real. O parser aceita o
  formato padrão do datasheet ELM327.
- **Q2.** Reenviar o pedido após `78` é seguro para os serviços de leitura
  listados, mas pode não ser o que o ECM espera. Alternativa: `ATMA` curto
  depois do prompt.
- **Q3.** Bluetooth adiciona latência; o intervalo do poller (hoje igual ao
  do J2534) pode precisar subir.
- **Q4.** `ATST` máximo ≈ 1 s. Se algum módulo demorar mais sem mandar `78`,
  o ELM devolve `NO DATA`.
