@echo off
rem Testes parados pendentes: scan-22 do cambio e dashboard (so leitura). Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro pendentes %*
echo.
pause
