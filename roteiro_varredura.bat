@echo off
rem Varredura longa de todos os IDs CAN (so leitura). Ignicao ligada. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro varredura %*
echo.
pause
