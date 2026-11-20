# Revisão do dashboard com o carro ligado

Rode `dashboard_carro.bat` (carro em P, freio de mão, motor ligado) e abra http://127.0.0.1:8000.
Marque o que funciona; o que não funcionar, anote o que apareceu na tela.

## Dados
- [ ] RPM, velocidade e temperatura do motor batem com o painel do carro
- [ ] Marcha/ré e O/D do câmbio mudam ao mexer na alavanca
- [ ] ATF aparece em °C com selo "estimado"
- [ ] Cada valor mostra o selo de confiança (padrão, confirmado, estimado, cru, indisponível)
- [ ] Valor sem dado mostra o motivo, não zero

## Falhas (DTC)
- [ ] Painel de falhas lista P0725, U1000 e P1722 do câmbio (igual ao `ler_erros.bat`)
- [ ] Lista vazia nunca aparece como "sem falhas"
- [ ] Não existe botão de apagar

## Robustez
- [ ] Tirar e pôr o cabo USB não derruba o dashboard
- [ ] Fechar com Ctrl+C libera o adaptador (o `ler_erros.bat` roda depois sem erro)

## Onde a comunidade pode acrescentar
- Novos veículos: `src/openscan_obd/profiles/` (veja `docs/adicionar-veiculo.md`)
- Novos painéis ou indicadores: `src/openscan_obd/static/dashboard.html`
- Novos decoders: `src/openscan_obd/gateway/`, sempre com teste offline
