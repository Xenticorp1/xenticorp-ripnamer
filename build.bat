@echo off
setlocal
REM Builds RipNamer.exe (single file, no console window) into .\dist\
cd /d "%~dp0"

if not exist ripnamer.py (
  echo ripnamer.py is missing from this folder.
  goto :err
)
if not exist ripnamer_app\ui\app.py (
  echo The ripnamer_app folder is missing - keep it next to ripnamer.py.
  goto :err
)

set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY (
  python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Python not found.
  echo Install it with:   winget install Python.Python.3.12
  echo   or from python.org ^(tick "Add python.exe to PATH"^).
  echo Then close this window and run build.bat again.
  goto :err
)

echo.
set "KEY="
set /p "KEY=Paste TMDb API key to bake into the exe (or just press Enter to skip): "
if exist ripnamer_key.py del ripnamer_key.py
if defined KEY (
  > ripnamer_key.py echo KEY = "%KEY%"
  echo Key will be built in.
) else (
  echo No key baked in - you'll enter it in the app.
)
echo.

REM Optional branding files - skipped if missing instead of failing
set "EXTRA="
if exist ripnamer_key.py set "EXTRA=--hidden-import ripnamer_key"
if exist xenticorp.ico (
  set "EXTRA=%EXTRA% --icon xenticorp.ico --add-data xenticorp.ico;."
) else (
  echo [note] xenticorp.ico not found - building without custom icon.
)
if exist version_info.txt (
  set "EXTRA=%EXTRA% --version-file version_info.txt"
) else (
  echo [note] version_info.txt not found - building without file details.
)

echo Using: %PY%
REM pillow lets PyInstaller accept a PNG renamed/used as the icon
%PY% -m pip install --upgrade pyinstaller sv-ttk pillow
if errorlevel 1 (
  echo.
  echo pip install failed - see the error above.
  goto :err
)

%PY% -m PyInstaller --noconfirm --onefile --windowed --name "Xenticorp Ripnamer" --clean --collect-data sv_ttk %EXTRA% ripnamer.py
if errorlevel 1 (
  echo.
  echo PyInstaller failed - see the error above.
  goto :err
)

if exist ripnamer_key.py del ripnamer_key.py
echo.
echo Done: %~dp0dist\Xenticorp Ripnamer.exe
pause
exit /b 0

:err
if exist ripnamer_key.py del ripnamer_key.py
echo.
echo Build failed. Screenshot everything above this line and send it over.
pause
exit /b 1
