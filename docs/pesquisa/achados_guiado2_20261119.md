# Achados do guiado parado, 2ª rodada (2026-11-19 20:38 coleta, 20:43 CAN)

Fontes: `coleta_20261119_203801.jsonl` (38 estímulos, todos os módulos a cada ciclo, 50 leituras por LID) e `sniff_20261119_204323.jsonl` (38 estímulos completos, ~33 MB). Carro parado em P, A/C ligado só no passo do A/C. Hipóteses por correlação com a hora do estímulo; janela = do 1,5 s depois do início ao fim do passo. Índices de byte do CAN começam em 0; os do KWP contam o cabeçalho `61 <lid>`. Bit = 0 é o menos significativo.

## CAN passivo (bits que viram em poucos passos)
| Estímulo | Bits que mudam (ID byte.bit) |
|---|---|
| Farol (baixo e alto, juntos) | 0x625 b1.6, 0x60D b0.2, 0x358 b1.7 |
| A/C ligado (e ventilador máx.) | 0x625 b1.7, 0x358 b1.6, 0x35D b0.0 (também 0x182 b2.1/b2.2) |
| Desembaçador traseiro | 0x551 b0.4 (e b0.7 invertido) |
| Limpador de para-brisa | 0x625 b0.2 |
| Porta aberta (qualquer) | 0x1F9 b0.6, 0x215 b1.2 (motorista e passageiro juntos) |
| Marcha engatada (R ou D) | 0x160 b0.1 = 0 (P/N = 1), 0x160 b0.2, 0x160 b2.5/b2.6, 0x174 b3.0 |
| Marcha R × D | 0x174 byte 3: P/N = 170, R = 153, D = 187; 0x177 byte 0: 90 só em R (254 nos demais) |
| Freio pisado | 0x35D byte 4 = 16 (0 solto), 0x354 byte 6 = 22 (6 solto) |
- Sem sinal nesta rodada: seta, volante, pisca-alerta (nem no CAN, nem nos LIDs).
- 0x160/0x180/0x1F9 repetem bytes uns dos outros (retransmissão).

## KWP (coleta, 50 leituras/LID)
- IPDM LID 10: byte 3 (240→244) e 16 (16→52) com A/C; byte 7 com farol baixo e A/C (96 e 128); bytes 13/14 com farol baixo; byte 6 com desembaçador e limpador; byte 11 só desembaçador; byte 12 só limpador.
- Meter LID 12: bytes 21/22 mudam com R, N e D (indicador de câmbio); byte 16 e meter LID 91 byte 8 com farol baixo.
- EPS LID 01 bytes 9/10 com seta esquerda (1 passo, a confirmar).
- BCM: nenhum LID mudou em nenhum estímulo (portas, luzes e setas não aparecem nos LIDs lidos do BCM).

## Pendente
- Confirmar no carro andando: velocidade das rodas nos IDs 0x284/0x285/0x354/0x355 (reescala), e se 0x174 byte 3 troca em P↔N.
- Seta e volante: não apareceram nos IDs vistos; pode estar em 0x002 (não passou no barramento) ou exigir carro em movimento.
