@echo off
rem Abre o dashboard com o carro ligado (GODIAG GD101, perfil Sentra B16) e grava uma captura. So leitura. Dois cliques.
rem Na primeira vez cria o ambiente Python (.venv) e instala o projeto; precisa de Python 3.10+ de 32 bits (driver GODIAG e 32 bits).
rem Depois abra http://127.0.0.1:8000 no navegador. Feche com Ctrl+C.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set TS=%%i
".venv\Scripts\python.exe" -m openscan_obd.cli dashboard --hardware ^
  --dll "C:\Program Files (x86)\GODIAG\GODIAG J2534 Driver\GODIAG_PT32.dll" ^
  --profile nissan-sentra-b16-2010 --capture "logs\dashboard_%TS%.jsonl" ^
  --vehicle "Nissan Sentra B16 2010" --adapter "GODIAG GD101" %*
echo.
pause
