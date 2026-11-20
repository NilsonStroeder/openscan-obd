# Fontes abertas verificadas (18/11/2026)

Autor: Nilson Stroeder Filho. Registro do que foi aberto e o que serve para o JF011E / Sentra B16.

## Serve (hipóteses a testar, não verdades)
- **stream4550, Torque Pro para Nissan C12 (Pulsar), câmbio CVT7 JF015E** (página tailandesa, fórmulas em imagens):
  - Câmbio, `21 01` no 7E1 (sessão `10C0`): RPM `I*32`, câmbio auxiliar `X` (0-2), pedal `Z*80/255`, temp. do óleo do câmbio `AJ-40`
    (letras do Torque: A = primeiro byte após `61 01`; I = índice 8, X = 23, Z = 25, AJ = 35).
  - Motor, serviço `22` (sessão `10C0`, parar com `1081`): `1106` temp. ar admissão `A-50`; `1114` sensor nível combustível (raw);
    `111F` temp. óleo motor `A-50`; `1178` ventoinha %; `1186` nível combustível (L); `122A` velocidade (cruise) `(A*256+B)*0.05625`;
    `122B` velocidade ajustada do cruise; `1278` pressão de óleo `(((A*256+B)/200)-0.75)*18.7` (aprox., ±10%).
  - Atenção: é outro modelo/câmbio (JF015E, C12). O layout do nosso JF011E pode diferir; confirmar na gravação.
- **balrog-kun/nissan-qashqai-can-info** (Qashqai J10, mesma plataforma C do Sentra B16): quadros periódicos do CAN
  (IDs 160/161 pedal, 284/285 rodas e velocidade, 002 volante, 354/355 velocidade, 19b/215 marcha, 421/41f/176 "informação do câmbio" nos automáticos, não decodificados).
  Serve de roteiro para a escuta passiva (`sniff`).

## Não serve
- openconsult (GPL-3.0): só Consult I, 14 pinos, 1989-2000.
- K11Consult: Consult serial; sem CAN nem CVT.
- elm327-scanner (MIT): PIDs padrão; sem definições Nissan.
- nissan-consult-3-plus-j2534: não foi possível abrir (limite de requisições); aparência de página promocional, não verificado.
