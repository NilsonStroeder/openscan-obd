@echo off
rem Dirigindo (so leitura): 15 min gravando + 5 min escutando o CAN, usando a ultima descoberta. Ex.: roteiro_gravacao.bat --fuel gasolina. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nao achei .venv\Scripts\python.exe nesta pasta.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro gravacao %*
echo.
pause
