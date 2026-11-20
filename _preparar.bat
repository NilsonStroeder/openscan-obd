@echo off
rem Usado pelos outros .bat: cria o ambiente Python (.venv) e instala o projeto na primeira vez.
rem O driver do GODIAG e de 32 bits, entao o Python tambem precisa ser de 32 bits.
if exist ".venv\Scripts\python.exe" exit /b 0
echo Primeira vez: criando o ambiente Python em .venv ...
py -3-32 -m venv .venv 2>nul || py -3 -m venv .venv 2>nul || python -m venv .venv 2>nul
if not exist ".venv\Scripts\python.exe" (
    echo Nao consegui criar o ambiente. Instale o Python 3.10 ou mais novo ^(32 bits^) em python.org e rode de novo.
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -e . || (
    echo Falha ao instalar as dependencias. Confira a internet e rode de novo.
    rmdir /s /q .venv
    exit /b 1
)
exit /b 0
