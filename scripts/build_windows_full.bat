@echo off
rem ==============================================================================
rem Automated 1-Click Windows Build & Packaging Script for Signal-Server GUI
rem ==============================================================================

echo [1/4] Checking Python environment...
python --version
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH! Please install Python 3.10+.
    pause
    exit /b 1
)

echo [2/4] Installing GUI dependencies and PyInstaller...
python -m pip install --upgrade pip
python -m pip install -r gui\requirements.txt
python -m pip install pyinstaller

echo [3/4] Ensuring directories exist...
if not exist "bin" mkdir "bin"

rem If signalserver.exe is not in bin\, look for it in Signal-Server\build\
if exist "Signal-Server\build\signalserver.exe" (
    copy /y "Signal-Server\build\signalserver.exe" "bin\"
    copy /y "Signal-Server\build\signalserverHD.exe" "bin\"
    copy /y "Signal-Server\build\signalserverLIDAR.exe" "bin\"
)
if exist "Signal-Server\utils\sdf\usgs2sdf\build\srtm2sdf.exe" (
    copy /y "Signal-Server\utils\sdf\usgs2sdf\build\srtm2sdf.exe" "bin\"
    copy /y "Signal-Server\utils\sdf\usgs2sdf\build\srtm2sdf-hd.exe" "bin\"
)

echo [4/4] Bundling Standalone Windows Executable via PyInstaller...
python scripts\package_windows.py

echo.
echo ==============================================================================
echo [SUCCESS] Standalone Application created in: dist\SignalServerGUI\
echo Launch 'dist\SignalServerGUI\SignalServerGUI.exe' to run the app.
echo Optional: Run Inno Setup on 'scripts\installer.iss' to produce the Setup.exe!
echo ==============================================================================
pause
