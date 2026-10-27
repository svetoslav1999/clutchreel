@echo off
setlocal EnableExtensions
chcp 65001 >nul
title ClutchReel - Actualizar
rem git pull puede reescribir este mismo .bat mientras cmd lo lee: se ejecuta una copia temporal.
if /I not "%~1"=="--desde-copia" (
    copy /y "%~f0" "%TEMP%\clutchreel_actualizar.bat" >nul
    "%TEMP%\clutchreel_actualizar.bat" --desde-copia "%~dp0"
)
cd /d "%~2"

echo ==========================================
echo   ClutchReel - actualizar a la ultima version
echo ==========================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [X] No se encontro Git. Instalalo con:  winget install Git.Git
    goto :fin_error
)
if not exist ".git" (
    echo [X] Esta carpeta no es un clon de Git de ClutchReel. Clonala con:
    echo     git clone https://github.com/svetoslav1999/clutchreel.git
    goto :fin_error
)

rem ---------- 1) Cambios locales: nunca se descartan ----------
set "DIRTY="
for /f "delims=" %%L in ('git status --porcelain -uno') do set "DIRTY=1"
if defined DIRTY (
    echo [!] Tienes cambios sin guardar en archivos de ClutchReel:
    git status --short -uno
    echo.
    echo     No se ha tocado nada. Para conservarlos, guardalos aparte y vuelve a ejecutar Actualizar.bat:
    echo         git stash push -m "mis cambios"
    echo     ^(despues de actualizar puedes recuperarlos con  git stash pop^)
    goto :fin_error
)

rem ---------- 2) Descargar y aplicar ----------
echo [..] Buscando actualizaciones...
git fetch origin
if errorlevel 1 (
    echo [X] No se pudo contactar con GitHub. Comprueba la conexion y que tienes acceso al repositorio.
    goto :fin_error
)
git pull --ff-only origin main
if errorlevel 1 (
    echo.
    echo [X] No se pudo actualizar: tu copia y la de GitHub tienen historiales distintos
    echo     ^(por ejemplo, porque el historial se reescribio o hiciste commits propios^).
    echo.
    echo     Para dejar tu copia igual que la de GitHub ^(se pierden tus commits locales^):
    echo         git branch copia-antes-de-actualizar
    echo         git reset --hard origin/main
    echo     y vuelve a ejecutar Actualizar.bat. La primera linea guarda tus commits por si los necesitas.
    echo     Tu configuracion de ClutchReel ^(%%APPDATA%%\ClutchReel^) no se toca.
    goto :fin_error
)

rem ---------- 3) Dependencias ----------
if not exist ".venv\Scripts\python.exe" (
    echo [!] No hay entorno de Python todavia: ejecuta Iniciar.bat para instalarlo.
    goto :fin_error
)
".venv\Scripts\python.exe" -I scripts\dependencias.py
if errorlevel 1 goto :fin_error

rem ---------- 4) Version instalada ----------
for /f "delims=" %%V in ('.venv\Scripts\python.exe -c "import clutchreel;print(clutchreel.__version__)"') do set "VER=%%V"
for /f "delims=" %%C in ('git log -1 --format^=%%h') do set "COMMIT=%%C"
echo.
echo [OK] ClutchReel %VER% ^(commit %COMMIT%^). Novedades en CHANGELOG.md
echo     Abre la app con Iniciar.bat
if not defined CLUTCHREEL_SIN_PAUSA pause
exit /b 0

:fin_error
echo.
if not defined CLUTCHREEL_SIN_PAUSA pause
exit /b 1
