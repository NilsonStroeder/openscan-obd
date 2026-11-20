@echo off
rem Relatorio de calibracao (combustivel, avanco, MAF, malha, puxadas) com todos os coleta_*.jsonl. Offline, nao usa o carro. Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m openscan_obd.cli analisar-log %*
echo.
pause
