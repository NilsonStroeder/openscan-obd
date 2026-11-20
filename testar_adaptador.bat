@echo off
rem Testa o adaptador GODIAG GD101: abre e fecha, sem enviar nada ao carro.
rem Basta dar dois cliques neste arquivo com o GD101 ligado no USB.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nao achei .venv\Scripts\python.exe nesta pasta.
    echo O ambiente do projeto precisa ser criado antes. Chame quem montou o projeto.
    pause
    exit /b 1
)
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" -m openscan_obd.cli j2534-check %*
echo.
pause
