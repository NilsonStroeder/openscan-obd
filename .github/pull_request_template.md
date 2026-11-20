## O que muda
<!-- Resumo curto -->

## Checklist
- [ ] Continua **somente leitura** (nada de escrita, rotinas, SecurityAccess, reset ou limpeza de DTC)
- [ ] Específico de um carro está em um **perfil**, não no fluxo genérico
- [ ] Bytes sem significado confirmado ficam crus ou marcados como hipótese
- [ ] Testes offline para parsers/decoders; `python -m pytest tests --ignore=tests/browser` passa
- [ ] Mexeu no dashboard? Rodei também `tests/browser`
- [ ] Nenhum VIN, placa, caminho pessoal ou dado pessoal nos arquivos enviados
