@echo off
rem Le os codigos de falha (motor, cambio, direcao, painel, carroceria, IPDM). So leitura: nao apaga nada. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro erros %*
echo.
pause
