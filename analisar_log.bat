@echo off
rem Relatorio de calibracao (combustivel, avanco, MAF, malha, puxadas) com todos os coleta_*.jsonl. Offline, nao usa o carro. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Nao achei .venv\Scripts\python.exe nesta pasta.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m openscan_obd.cli analisar-log %*
echo.
pause
