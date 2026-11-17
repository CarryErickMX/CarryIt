@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo No se encontro el entorno de Python. Ejecuta primero "instalar.bat".
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" main.py
