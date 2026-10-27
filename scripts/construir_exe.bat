@echo off
setlocal
cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo Ejecuta primero Iniciar.bat para crear el entorno.
    pause
    exit /b 1
)
set "VPY=.venv\Scripts\python.exe"
"%VPY%" -m pip install pyinstaller==6.22.3 --quiet --disable-pip-version-check
rem Se genera una CARPETA (--onedir), no un solo .exe: PySide6/Qt van bajo LGPL-3.0 y el usuario
rem debe poder sustituir sus DLL. FFmpeg NO se copia dentro de dist\ (no se redistribuye; la app lo
rem busca en tools\ffmpeg junto al ejecutable, en el PATH o en la ruta de Ajustes).
"%VPY%" -m PyInstaller --noconfirm --clean --onedir ^
    --name ClutchReel --windowed ^
    --collect-all demoparser2 ^
    --collect-submodules PySide6.QtMultimedia ^
    --add-data "assets;assets" ^
    --paths . ^
    clutchreel\__main__.py
if errorlevel 1 (
    echo Fallo la construccion del ejecutable.
    pause
    exit /b 1
)
echo.
echo Ejecutable creado en dist\ClutchReel\ClutchReel.exe
echo FFmpeg no se incluye: copia tools\ffmpeg junto al .exe o instala FFmpeg (ver README).
pause
