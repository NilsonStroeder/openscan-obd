# Contribuindo

Obrigado pelo interesse! Princípios que o projeto segue (veja também `AGENTS.md`):

1. **Somente leitura.** Nenhum PR deve adicionar escrita, rotinas, SecurityAccess, reset ou limpeza de DTC.
   Serviços novos entram na allow-list de `ReadOnlyDevice` só com justificativa e teste.
2. **Bytes crus primeiro.** Se o significado, tamanho ou escala não está confirmado, preserve o hex e
   marque como hipótese (`hipotese_nao_validada`, selo `cru`/`estimado`).
3. **Específico de carro fica em perfil**, nunca no fluxo genérico.
4. **Sem alegar compatibilidade** com base em um carro só. Registre veículo, módulo, adaptador e evidência.
5. **Testes offline** para parsers e decoders; ninguém precisa de um carro para rodar a suíte.

## Fluxo

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt && pip install -e . pytest
python -m pytest tests --ignore=tests/browser
```

Escreva o teste antes (TDD), rode a suíte inteira e só então abra o PR. Textos e docs em português ou inglês.

## Enviando logs de outro carro

Antes de anexar qualquer arquivo de `logs/`: remova **VIN** (texto e hex), placas, caminhos do seu
computador e qualquer dado pessoal. Prefira anexar só o trecho relevante. Veja `docs/exemplos/`.
Para adicionar um veículo, leia [`docs/adicionar-veiculo.md`](docs/adicionar-veiculo.md).

## Reportando problemas

Informe: carro (marca/modelo/ano/motor/câmbio), adaptador e driver, comando executado, saída
e se o carro estava parado com ignição ligada. Nunca teste algo novo com o carro em movimento.
