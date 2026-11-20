@echo off
rem Abre o roteiro guiado do teste no carro com o Python de 32 bits do projeto.
rem Basta dar dois cliques neste arquivo.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py %*
echo.
pause
