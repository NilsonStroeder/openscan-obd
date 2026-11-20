# Como compartilhar logs sem expor seu carro

Os arquivos em `logs/` guardam respostas cruas do carro e **podem conter o VIN** (chassi), em texto e em hex.
Antes de anexar qualquer um em uma issue ou PR:

1. Procure o VIN (17 caracteres) no arquivo e troque por `*****************`. Procure também a versão em hex
   (cada caractere vira 2 dígitos hex, ex. `3` = `33`).
2. Remova placas, nomes, e-mails e caminhos do seu computador (`C:\Users\...`).
3. Prefira anexar só o trecho relevante, não a captura inteira.
4. Diga o carro (marca, modelo, ano, motor, câmbio) e o adaptador no texto da issue, não no arquivo.

Exemplos já limpos estão em `docs/exemplos/`. Dúvida se algo é pessoal? Não anexe e pergunte na issue.
