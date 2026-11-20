# Achados do roteiro guiado parado (2026-11-19, 20:24)

Fonte: `coleta_20261119_202407.jsonl` (38 estímulos, completo). A escuta CAN (`sniff_20261119_202925.jsonl`) parou após ~55 s (só repouso, freio, pedal leve/médio) e precisa ser refeita. Índices de byte contam o cabeçalho `61 <lid>`. Hipóteses; módulos lentos (BCM, IPDM, meter, EPS) foram lidos só a cada ~22 s, então estímulos de 6–8 s foram amostrados por acaso.

## TCM LID 01 (lido a cada ciclo)
- **Engatado (R/D) × não engatado (P/N)**, com pé no freio: bytes 42, 43, 44, 45, 48, 54, 55, 59, 62, 63, 64 mudam juntos. Ex.: byte 43 = 121 em P/N e 10 em R/D; byte 54 = 3 em P/N e 31 em R/D; bytes 62/63 = 17/18 em P/N e 0/2 em R/D. R e D deram os mesmos valores na janela final de cada passo: **R × D ainda não separados** neste LID.
- **Pedal**: byte 45 cai com o pedal (142 repouso, 106 leve, 28 médio/forte); byte 37 sobe (66, 79, 109); bytes 20–23 vão de 0 a ~20–29; byte 39 vai de 254 a 130 com pedal ≥ médio. Candidatos a abertura do acelerador, a confirmar com a leitura simultânea do PID 45/11.
- Rotação OBD acompanhou o pedal: ~790 (repouso), 2048 (leve), 3254 (forte).

## IPDM LID 10 (só 14 amostras)
- Farol baixo: byte 7 = 96, byte 13 = 4, byte 14 = 128.
- A/C ligado: byte 7 = 128, byte 16 = 52, byte 3 = 244.

## Pouco claro
- ECM DIDs 1219/121A mudaram só em `seta_dir` (1 amostra, pode ser coincidência).
- ECM DID 120D/120E/120F e 1208/120B variaram com pedal e carga elétrica (A/C, volante, câmbio).
- Meter LID 12 bytes 21/22 mudaram em `cambio_p`; meter LID 91 bytes 3/4 mudaram depois do primeiro freio.

## CAN (55 s)
- 0x35D byte 4 (0 → 16) e 0x354 byte 6 (6 → 22) mudaram com o freio.
- 0x284/0x285 bytes 6/7 trocaram de valor com o pedal (112 ↔ 143), possivelmente contador.

## Ajuste feito
- Com `--estimulos`, a coleta agora lê **todos os módulos a cada ciclo**.
