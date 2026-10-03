@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "PANEL=%ROOT%web_panel"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

echo.
echo  Local Minecraft Server Panel
if not exist "%PYTHON%" (
  call :find_python
  if errorlevel 1 call :install_python
  if errorlevel 1 goto :python_error
  %BOOTSTRAP_PYTHON% %BOOTSTRAP_PYTHON_ARGS% -c "import sys; raise SystemExit(sys.version_info < (3, 11))" || goto :python_error
  echo  Creating the local Python environment...
  %BOOTSTRAP_PYTHON% %BOOTSTRAP_PYTHON_ARGS% -m venv "%ROOT%.venv" || goto :python_error
)

echo  Checking panel dependencies...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r "%PANEL%\requirements.txt" || goto :deps_error

echo  Starting the panel. Your browser will open when it is ready.
cd /d "%PANEL%"
"%PYTHON%" run_panel.py
goto :end

:python_error
echo Python 3.11 or newer is needed to start the panel.
echo Install it from https://www.python.org/downloads/ and run this file again.
pause
exit /b 1

:deps_error
echo The panel dependencies could not be installed. Check your Internet connection and run this file again.
pause
exit /b 1

:end
endlocal
exit /b 0

:find_python
set "BOOTSTRAP_PYTHON="
set "BOOTSTRAP_PYTHON_ARGS="
where py >nul 2>nul
if not errorlevel 1 (
  set "BOOTSTRAP_PYTHON=py"
  set "BOOTSTRAP_PYTHON_ARGS=-3"
  exit /b 0
)
where python >nul 2>nul
if not errorlevel 1 (
  set "BOOTSTRAP_PYTHON=python"
  exit /b 0
)
exit /b 1

:install_python
where winget >nul 2>nul
if errorlevel 1 exit /b 1
echo  Python is missing. Installing it once with Windows Package Manager...
winget install --id Python.Python.3.13 --exact --silent --accept-package-agreements --accept-source-agreements
call :find_python
exit /b %errorlevel%