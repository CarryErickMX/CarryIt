@echo off
setlocal
cd /d "%~dp0"
echo === CarryIt: instalacion ===
echo.

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
if not defined PY (
    echo Python no esta instalado. Instalando Python 3.12 con winget...
    winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
    set "PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe""
)

if not exist ".venv\Scripts\python.exe" (
    echo Creando entorno virtual...
    %PY% -m venv .venv || goto :error
)

echo Instalando dependencias (yt-dlp, customtkinter, pillow, deno)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error

where ffmpeg >nul 2>nul
if errorlevel 1 (
    if not exist "%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe" (
        echo Instalando FFmpeg con winget...
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    )
)

echo Creando accesos directos en el Escritorio y en el menu Inicio...
".venv\Scripts\python.exe" accesos.py

echo.
echo Listo. Abre la app con el icono "CarryIt" del Escritorio o del menu Inicio.
pause
exit /b 0

:error
echo.
echo Ocurrio un error durante la instalacion.
pause
exit /b 1
