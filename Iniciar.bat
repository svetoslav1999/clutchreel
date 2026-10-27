@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title ClutchReel
cd /d "%~dp0"

echo ==========================================
echo   ClutchReel - demos de CS2 a highlights
echo ==========================================
echo.

rem ---------- 1) Python 3.11+ ----------
set "PY="
for %%V in (3.13 3.12 3.11 3.14) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY (
            "%%P" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" >nul 2>&1 && set "PY=%%P"
        )
    )
)
if not defined PY (
    echo [X] No se encontro Python 3.11 o superior.
    echo.
    echo     Opcion A: instalarlo con winget ^(recomendado^):
    echo         winget install --id Python.Python.3.12 -e --source winget
    echo     Opcion B: descargarlo de https://www.python.org/downloads/windows/
    echo         ^(marca "Add python.exe to PATH" al instalar^)
    echo.
    choice /C SN /M "Quieres que intente instalarlo ahora con winget (S/N)?"
    if errorlevel 2 goto :fin_error
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    echo.
    echo Instalacion terminada. Cierra esta ventana y vuelve a ejecutar Iniciar.bat.
    goto :fin_error
)
for /f "delims=" %%I in ('%PY% -c "import sys;print(sys.version.split()[0])"') do set "PYVER=%%I"
echo [OK] Python %PYVER%

rem ---------- 2) Entorno virtual + dependencias ----------
if not exist ".venv\Scripts\python.exe" (
    echo [..] Creando entorno virtual ^(solo la primera vez^)...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [X] No se pudo crear el entorno virtual.
        goto :fin_error
    )
)
set "VPY=.venv\Scripts\python.exe"
rem Reinstala solo si cambia el contenido de requirements.txt (huella en .venv\.instalado) y quita
rem los paquetes que la version nueva ya no usa (p. ej. obsws-python en la 1.1.0).
"%VPY%" -I scripts\dependencias.py
if errorlevel 1 goto :fin_error
rem «Iniciar.bat --solo-instalar»: prepara el entorno sin abrir la app (lo usan las pruebas).
if /I "%~1"=="--solo-instalar" (
    echo [OK] Entorno listo
    exit /b 0
)

rem ---------- 3) FFmpeg ----------
"%VPY%" -I scripts\obtener_ffmpeg.py
if errorlevel 1 (
    echo [!] FFmpeg no esta disponible. La app funcionara pero no podra exportar video.
    echo     Puedes instalarlo con:  winget install Gyan.FFmpeg
)

rem ---------- 4) Lanzar ----------
echo [..] Abriendo ClutchReel...
"%VPY%" -m clutchreel %*
if errorlevel 1 (
    echo.
    echo [X] ClutchReel termino con error. Revisa el registro en:
    echo     %APPDATA%\ClutchReel\logs\clutchreel.log
    goto :fin_error
)
exit /b 0

:fin_error
echo.
pause
exit /b 1
