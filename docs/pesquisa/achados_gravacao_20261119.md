# Achados da gravação em movimento (2026-11-19)

Fontes: `coleta_20261119_165634.jsonl` (15 min, 193 ciclos, etanol) e `sniff_20261119_171237.jsonl` (5 min, 352 383 quadros, 28 IDs). Todos os números abaixo são **correlações com PIDs OBD gravados no mesmo instante**; são hipóteses até haver estímulo controlado. Índices de byte contam o cabeçalho de resposta (`61 <lid>` / `62 <did>`).

## Velocidade (OBD 0D, máx. 112 km/h)
- `meter` LID 12, byte 4 e byte 6: r=0,998; km/h ≈ 2,55·byte + 1 (byte máx. 41).
- `eps` LID 01, byte 14: r=0,995; km/h ≈ 2,55·byte + 1,3.
- `tcm_cvt` LID 01, bytes 4, 5, 12, 13, 15: r≈0,985; byte 13 ≈ km/h direto (1,00·byte).
- ECM DID 122A/122B: u16 de bytes 3-4, r=0,972, fator ≈ 0,0559 (guia tailandês: 0,05625).
- ECM DID 1102 byte 3: r=0,976, ≈ 2·byte.

## Rotação (OBD 0C, 613–3772 rpm)
- `meter` LID 12, byte 8: r=0,975; rpm ≈ 33·byte (erro rms ~95 rpm).
- ECM DID 1219/121A: r=0,74 (fraca; provavelmente outra grandeza ligada à carga).

## Outros
- ECM DID 1106 byte 3: r=−0,87 com velocidade, compatível com temperatura do ar de admissão (A−50) esfriando em movimento.
- `ipdm` LID 10 bytes 3 e 16: 2 valores, r=−0,89 com velocidade (estado ligado/desligado ligado ao movimento).
- `tcm_cvt` LID 01 bytes com poucos valores: 11 (174–181), 41, 42/48, 44/50, 46/52, 54, 55, 59, 61 (4–10), 62–68. Candidatos a marcha, modo e travamento; falta estímulo para nomear.
- LIDs do TCM 17, 19, 1B, 1D, 1F: `status: error` em todos os 193 ciclos; LID 22: NRC 12. EPS LID 90: NRC 22. BCM LID 33: NRC 12 (nesta gravação).
- ECM: dos DIDs lidos, 1100/1101/112D/112E/1140/1147/1148/1150/1180/1181/1184/1185/1200/1201/121B/121C/1220–1223/1240 não variaram em 15 min.

## CAN passivo (28 IDs, 100/50/25/10 Hz)
- 0x284/0x285/0x280/0x354/0x355: u16 nos bytes 0-1 e 2-3 (até 26 200) e u16 nos bytes 4-5 / 0-1 (até 12 555) se comportam como velocidades de rodas e do veículo, como no Qashqai J10. Fatores ainda não calibrados: a escuta CAN não roda junto com o OBD.
- 0x160/0x180: 0x180 repete os bytes de 0x160 deslocados 2 posições (retransmissão).
- 0x421, 0x35D, 0x60D, 0x625: poucos valores; candidatos a estados (marcha/modo).
- IDs 0x2DE, 0x215/0x216, 0x300, 0x551, 0x560, 0x580 sem referência ainda.

## Próximo
Roteiro guiado com marcas de hora por estímulo (pedal, freio, ré, volante, faróis) para nomear os bytes e calibrar os IDs do CAN.
