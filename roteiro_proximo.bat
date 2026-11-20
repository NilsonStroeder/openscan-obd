@echo off
rem Roteiro do PROXIMO teste no carro (so o que falta validar). Dois cliques.
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0_preparar.bat" || (
    pause
    exit /b 1
)
".venv\Scripts\python.exe" roteiro_carro.py --roteiro proximo %*
echo.
pause
