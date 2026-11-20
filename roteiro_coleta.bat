@echo off
rem Coleta ampla (so leitura): descoberta parado, 15 min gravando e 5 min de escuta do CAN. Ex.: roteiro_coleta.bat --fuel gasolina. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro coleta %*
echo.
pause
