# Achados do roteiro andando — 20/11/2026

Autor: Nilson Stroeder Filho. Carro: Sentra B16 2010, flex (etanol no tanque). Logs: `erros_antes/depois_20261120_*`, `coleta_20261120_091509` (trajeto a frio, 11 min), `coleta_20261120_092703` (andando guiado), `sniff_20261120_093217` (CAN, ainda não analisado), `coleta_20261120_093723` (puxada).

## Códigos de falha (medido)
- Antes e depois de andar a leitura foi idêntica: TCM com P0725, U1000 e P1722 (status cru f1, a7, f1), os mesmos três de 16/11. Nenhum código novo depois de andar ou puxar.
- ECM (03/07): 0 códigos. EPS, painel, BCM e IPDM responderam `57 00` (0 códigos). Modo 0A da ECM sem resposta.
- Leitura: os três continuam armazenados; não sabemos se estão ativos (o status cru não tem significado conhecido).

## Velocidade (correlação alta; calibração a refinar)
- OBD 0D vs bytes: meter LID12 b4/b6 e EPS LID01 b14 ≈ 2,56 km/h por unidade (r 0,998–0,999); TCM LID01 b4/b5/b12 ≈ 1,0 km/h por unidade (r 0,991); DID ECM 1102 b3 ≈ 2 km/h por unidade. A cadência de ~6 s por ciclo deixa erros de até 17 km/h em trechos de aceleração: a inclinação é confiável, o erro máximo não.

## Temperatura do fluido do TCM (estimada pela tabela do ESM, já usada no dashboard)
- O dashboard já decodifica o ATF: `b[30]` do payload do LID 01 (= byte 31 da resposta crua `61 01 ...`) pela tabela do ESM, nível "estimado" (decisão de 15/11). Nos logs de hoje esse byte vai de 75 (início do trajeto) a 126 (fim do andando), ou seja, de ~36 °C a ~61 °C pela tabela. O byte 10 da resposta crua (`b[9]`, candidato antigo) é o complemento (soma ≈ 255) e cai de 180 para 128.
- Correção: eu havia escrito que a conversão em °C não existia; existe, só não é validada contra uma referência externa. O boletim da Nissan que cita "contagem 158–161 para 70–80 °C" é compatível com a tabela (80 °C ≈ contagem 160 pelo ESM), não com o byte 10.
- Pendente: confirmar a tabela com uma temperatura de referência (Consult da loja ou termômetro no cárter).

## O/D OFF (medido)
- A ~67 km/h: O/D ligado 1506 rpm; O/D desligado 3420 rpm; religado 1392 rpm. Com O/D desligado a rotação mais que dobra.

## Puxadas (medido, OBD)
- Três puxadas (6–8 s): 3600→5980 rpm, até 117 km/h, carga 100%, borboleta até 80%, avanço 16–24°, lambda comandado 0,90–0,91.
- LTFT constante em +20,3% em TODAS as células de rotação e carga, inclusive carga plena: parece compensação fixa de combustível (flex), não aprendizado de erro. A confirmar com gasolina.
- Sem detonação nem sonda larga: não dá para validar mistura em carga plena.

## Pendente
- Calibrar CAN de velocidade das rodas no sniff; achar byte do O/D; decodificar temperatura em °C; cadência de ~6 s no andando é alta demais para transientes (ver puxada, 4,5 Hz).

## Análise offline do CAN e do O/D (mesmo dia, sem o carro)

**Velocidade no CAN (sniff, 8 patamares).** Correlação 0,999–1,000 com a velocidade nominal dos patamares:
- Um byte de velocidade única em 0x354 b0, 0x355 b0, 0x28C b0, 0x280 b4 e 0x284 b4: ≈ 2,69 km/h por unidade contra a velocidade nominal; contra o OBD real (que ficou ~4% abaixo do nominal) fica ≈ 2,56 km/h por unidade, igual ao byte do painel/EPS. Faixa 0–34 até 90 km/h.
- 0x284 e 0x285, bytes 0 e 2: ≈ 1,27 km/h por unidade (provavelmente rodas individuais). 0x285 b4: ≈ 1,04 km/h por unidade.
- 0x176 b0: ≈ 5,76 km/h por unidade (faixa 0–16; saturado ou outra grandeza).
- Limitação: o sniff não tem velocidade de referência (OBD), usei a nominal dos patamares; a escala exata sai de rodar o `sniff` com OBD em paralelo ou do trecho a 90 km/h.

**O/D OFF (3 sinais independentes, confirmados no mesmo trecho de 20 s):**
- TCM LID01 byte 64: 1 com O/D OFF, 0 com O/D ligado (antes e depois). Byte 60: 48 contra 0. Byte 8: 60 contra 39.
- Painel (meter) LID12 byte 23: 32 (bit 5) contra 0: provavelmente a luz O/D OFF do painel.
- CAN: 0x421 b0 bits 0 e 2; 0x174 b2 bit 7; 0x176 b2 bit 3 e b4 bit 6; 0x177 b1 bits 4–5; 0x180 b0 bit 6; 0x1F9 b2 bit 6. Parte deles pode ser efeito da rotação mais alta, não do botão; o TCM byte 64 e o painel byte 23 são os mais limpos.
- Fica sem repetição: cada run teve uma única ocorrência do O/D OFF.

**Temperatura do fluido:** já existe conversão em °C (tabela do ESM, estimada). O que falta é uma referência externa para validar.
