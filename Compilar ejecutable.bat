@echo off
REM Compila el ejecutable de escritorio del informe diario.
REM Doble clic en este archivo; no hace falta abrir terminal ni VS Code.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0compilar.ps1"
echo.
pause
