@echo off
rem Descoberta de PIDs e LIDs com o carro parado e ligado (so leitura). Rode antes de roteiro_gravacao.bat. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro descoberta %*
echo.
pause
