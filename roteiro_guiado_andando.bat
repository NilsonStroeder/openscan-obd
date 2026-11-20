@echo off
rem ANDANDO em via reta (so leitura): estimulos guiados com hora marcada, coleta + escuta do CAN, usando a ultima descoberta. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nao achei .venv\Scripts\python.exe nesta pasta.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro guiado_andando %*
echo.
pause
