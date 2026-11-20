@echo off
rem Teste em movimento: captura do dashboard na estrada (so leitura). Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nao achei .venv\Scripts\python.exe nesta pasta.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro estrada %*
echo.
pause
