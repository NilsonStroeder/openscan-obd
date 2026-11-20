@echo off
rem Varredura longa do servico 22 (DIDs 0000-FFFF), so leitura. Pode levar horas; Ctrl+C salva o que achou. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro dids %*
echo.
pause
