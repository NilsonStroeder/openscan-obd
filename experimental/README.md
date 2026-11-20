# experimental/ — abordagens arquivadas

Código de caminhos que tentamos e que NÃO fazem parte do scanner atual.
Guardado pelo histórico de aprendizado, fora da raiz pra não confundir.

## Sniffing passivo via ELM327 (ATMA) — NÃO funciona no GD101
- `capture.py`, `analyze.py`, `elm_probe.py`, `tests/test_capture_fake_serial.py`
- Motivo: o GD101 confirma os comandos AT (inclusive ATMA) mas não faz o
  streaming de monitor passivo de fato — em 3 tentativas, zero frames
  (ver docs/protocol_notes.md). O caminho que funciona é J2534 ativo.

## Scripts de investigação pontual (superados)
- `examples_read_vin.py` — teste de conexão J2534 (superado por `scan`)
- `examples_read_tcu.py`, `examples_read_dtc_tcu.py` — sondas manuais do TCM
  (superadas por `probe-kwp`/`snapshot`)
- `examples_sanity_bogus_address.py` — teste de sanidade de filtro de ID (já cumpriu o papel)

Estes arquivos podem ter imports quebrados (dependiam de módulos que foram
movidos). Não são mantidos. Se algum dia um deles voltar a ser útil, é só
trazer de volta e consertar os imports.
