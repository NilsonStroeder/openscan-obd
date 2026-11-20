# Prompt para agentes de pesquisa: LTFT alto no Sentra B16 (MR20DE, flex)

Autor: Nilson Stroeder Filho. Data: 2026-11-18. Uso: colar em outro agente/chat com busca na web.

---

## Tarefa

Pesquise e responda **somente com fonte citada** (link + trecho curto) sobre o ajuste de combustível de longo prazo (LTFT)
de um Nissan Sentra B16 2.0 flex (motor MR20DE, câmbio CVT JF011E, Brasil, 2010). **Não chute.** Se não achar, escreva
"NÃO ENCONTRADO" naquele item. Não complete lacunas com conhecimento geral sem avisar.

## Regras anti-chute

1. Cada número (faixa, limite, valor de referência) precisa de: fonte, página/seção e geração do carro à qual se aplica.
2. Separe sempre por geração: **B16 (2007–2012, MR20DE 2.0)** é o nosso. B17 (MRA8DE 1.8) e B18 (MR20DD 2020+) são
   outros motores. Valores desses só entram marcados como "outra geração, indicativo".
3. Prefira, nesta ordem: manual de serviço Nissan (ESM, seção EC), boletins técnicos Nissan (NTB/TSB), documentação
   do padrão (SAE J1979/ISO 15031-5). Fórum e blog só como indício, e rotule assim.
4. Diga explicitamente quando duas fontes discordarem.
5. Não proponha reparos nem peças. Só o que as fontes dizem sobre faixas normais e causas.

## Dados medidos (leitura OBD-II padrão, só leitura, motor quente, 2026-11-16 e 11-18)

| Item | Valor |
|---|---|
| LTFT (PID 07) | +20,31 % em 16/11 (em 3 capturas, de 33 a 85 °C de líquido) e +21,09 % em 18/11 |
| STFT (PID 06) | mediana ~0 %; p5 a p95 de −4,7 a +5,5 %; marcha lenta −1,6 %; carga alta +0,8 % |
| MAF, marcha lenta quente em P (16/11) | 2,41 g/s a 693 rpm; carga calculada 20,4 %; TPS 12,5 % |
| MAF, parado em D com freio (18/11) | 4,6 g/s a 692 rpm; carga 42 % (condição diferente da anterior) |
| Lambda comandado (PID 44) | 1,00 em ~94 % do tempo; 0,81 a pleno acelerador; 1,9999 em desaceleração (corte) |
| O2 a montante (PID 14) | marcha lenta quente: p10 0,12 V, mediana 0,66 V, p90 0,72 V, 22 cruzamentos de 0,45 V em ~1.000 leituras |
| Tensão, ECT, IAT | 13,3–14,4 V; 78–91 °C; 33–37 °C |
| DTCs OBD (03/07/0A) | vazios (nenhum P0171/P0172 armazenado) |
| Condição | flex; combustível do último abastecimento: **desconhecido** (pergunte ao usuário, não presuma) |

## Perguntas

1. **Faixa normal e limite do trim em Nissan:** o que o manual de serviço diz sobre A/F ALPHA (valor combinado) e como
   ele se relaciona com os PIDs OBD-II 06/07 (STFT/LTFT) nessa ECU? O PID 07 reflete só o aprendizado ou o combinado?
   Qual faixa é "normal" (a fonte da Nissan fala em 90–110 % de A/F ALPHA para algumas gerações; confirmar para MR20DE B16).
2. **Limite de saturação:** em que valor de LTFT a ECU do MR20DE B16 grava P0171/P0174/P1273 ou similar? +21 % sem DTC é
   esperado?
3. **Valores de referência do B16 (MR20DE)** no ESM, seção EC (Trouble Diagnosis, Specification Value e CONSULT-III
   Reference Value in Data Monitor): MAF em marcha lenta quente e a 2.500 rpm; carga calculada em marcha lenta e a
   2.500 rpm; ponto de ignição em marcha lenta (CVT em P/N); rotação de marcha lenta. Dê o número e a condição exata.
4. **Sensor O2 a montante do MR20DE B16:** é de banda estreita ou "A/F sensor" de banda larga? Se for banda larga, o PID
   OBD 14 (tensão) é o que se espera ou a leitura correta seria o PID 24? O que é normal aparecer em 0,12–0,72 V?
5. **Etanol:** a ECU flex do MR20DE brasileiro estima/mede a mistura? Quanto o LTFT sobe ao abastecer com gasolina
   brasileira (E27 a E30) ou etanol, em relação ao esperado para gasolina pura? Há informação oficial de que o
   aprendizado de combustível precisa de quantos ciclos/km para estabilizar após troca de combustível?
6. **Cruzamento de indicadores:** quais combinações de LTFT, STFT, MAF, carga calculada e O2 a montante os manuais ou
   boletins usam para separar (a) ar falso/vazamento de vácuo, (b) MAF subestimando, (c) pressão/entrega de combustível
   baixa e (d) combustível com mais etanol? Tabela com a fonte de cada critério.
7. **Boletins:** existe NTB/TSB Nissan para B16 (2007–2012) sobre trim alto, P0101/MAF, mangueira de admissão
   rachada (air intake boot) ou reprogramação da ECM? Número, data e resumo.
8. **Zerar o aprendizado:** o ESM descreve limpar o valor de auto-aprendizado (self-learning) como parte do reparo?
   Só descreva o que a fonte diz; não é para executar nada.

## Formato da resposta

Uma tabela por pergunta: Afirmação | Valor | Condição | Geração | Fonte (link) | Trecho curto (até 15 palavras) |
Confiança (alta = manual/boletim; média = fonte técnica secundária; baixa = fórum). No fim, uma lista "NÃO ENCONTRADO"
e outra "fontes que discordam".
