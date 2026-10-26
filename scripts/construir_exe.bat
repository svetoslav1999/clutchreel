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
"%VPY%" -m PyInstaller --noconfirm --clean ^
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
if exist "tools\ffmpeg" xcopy /E /I /Y "tools\ffmpeg" "dist\ClutchReel\tools\ffmpeg" >nul
echo.
echo Ejecutable creado en dist\ClutchReel\ClutchReel.exe
pause
