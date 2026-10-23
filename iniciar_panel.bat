@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Keep this file ASCII-only with CRLF line endings: cmd.exe parses it with
rem the OEM code page and mis-handles labels in LF-only batch files.
rem Avoid parenthesized blocks that expand paths or variables set inside the
rem same block: cmd.exe expands them before the block runs, and a folder such
rem as "craft-panel (1)" would close the block early.
title Panel Minecraft
set "ROOT=%~dp0"
set "PANEL=%ROOT%web_panel"
set "VENV=%ROOT%.venv"
set "PYTHON=%ROOT%.venv\Scripts\python.exe"

echo.
echo  Panel local del servidor de Minecraft
echo.

if not exist "%PYTHON%" goto :create_venv
rem A venv stops working when the Python it was created from is uninstalled.
"%PYTHON%" -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul <nul
if "%errorlevel%"=="0" goto :install_deps
echo  El entorno de Python de la carpeta .venv no funciona. Se va a crear de nuevo...
rmdir /s /q "%VENV%" >nul 2>nul
if exist "%VENV%" goto :venv_locked

:create_venv
call :find_python
if "%errorlevel%"=="0" goto :make_venv
call :install_python
if not "%errorlevel%"=="0" goto :python_error
call :find_python
if not "%errorlevel%"=="0" goto :python_restart

:make_venv
echo  Creando el entorno local de Python. Solo ocurre la primera vez...
"%BOOTSTRAP_PYTHON%" %BOOTSTRAP_ARGS% -m venv "%VENV%"
if not "%errorlevel%"=="0" goto :venv_error
if not exist "%PYTHON%" goto :venv_error

:install_deps
echo  Revisando las dependencias del panel...
"%PYTHON%" -m pip install --disable-pip-version-check -q -r "%PANEL%\requirements.txt"
if not "%errorlevel%"=="0" goto :deps_error

echo  Iniciando el panel. El navegador se abrira cuando este listo.
echo  No cierres esta ventana mientras uses el panel.
cd /d "%PANEL%"
"%PYTHON%" run_panel.py
if not "%errorlevel%"=="0" goto :panel_error
endlocal
exit /b 0

:python_error
echo.
echo  [ERROR] Se necesita Python 3.11 o superior para iniciar el panel.
echo  1. Descargalo desde https://www.python.org/downloads/
echo  2. Durante la instalacion marca la casilla "Add python.exe to PATH".
echo  3. Vuelve a abrir este archivo.
echo  Si al escribir python se abre Microsoft Store, busca "Alias de ejecucion
echo  de aplicaciones" en Configuracion de Windows y desactiva python.exe y python3.exe.
echo.
pause
exit /b 1

:python_restart
echo.
echo  Python se instalo, pero esta ventana todavia no lo encuentra.
echo  Cierra esta ventana y vuelve a abrir iniciar_panel.bat.
echo.
pause
exit /b 1

:venv_locked
echo.
echo  [ERROR] No se pudo borrar la carpeta .venv porque esta en uso.
echo  Cierra las otras ventanas del panel y vuelve a abrir este archivo.
echo.
pause
exit /b 1

:venv_error
echo.
echo  [ERROR] No se pudo crear el entorno de Python en la carpeta .venv.
echo  Revisa que la carpeta del panel no sea de solo lectura y que el antivirus
echo  no la este bloqueando. Despues vuelve a abrir este archivo.
echo.
pause
exit /b 1

:deps_error
echo.
echo  [ERROR] No se pudieron instalar las dependencias del panel.
echo  Revisa tu conexion a Internet y vuelve a abrir este archivo.
echo  Si el error se repite, borra la carpeta .venv y vuelve a intentarlo.
echo.
pause
exit /b 1

:panel_error
echo.
echo  [ERROR] El panel se cerro con un error. Revisa los mensajes de arriba.
echo.
pause
exit /b 1

:find_python
set "BOOTSTRAP_PYTHON="
set "BOOTSTRAP_ARGS="
rem Every candidate is executed: the Microsoft Store "python.exe" alias is a
rem stub that only offers to install Python, so finding it on PATH is not enough.
call :try_python py -3 && exit /b 0
call :try_python python && exit /b 0
call :try_python python3 && exit /b 0
rem Right after a winget install, PATH is not refreshed in this window yet, and
rem some installs skip the "Add to PATH" option: probe the default locations.
call :try_python "%LOCALAPPDATA%\Programs\Python\Launcher\py.exe" -3 && exit /b 0
call :try_python "%SystemRoot%\py.exe" -3 && exit /b 0
for %%V in (314 313 312 311) do call :try_python "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" && exit /b 0
for %%V in (314 313 312 311) do call :try_python "%ProgramFiles%\Python%%V\python.exe" && exit /b 0
exit /b 1

:try_python
rem %1 is the interpreter and %2 an optional selector for the py launcher.
"%~1" %2 -c "import sys; raise SystemExit(sys.version_info < (3, 11))" >nul 2>nul <nul
if not "%errorlevel%"=="0" exit /b 1
set "BOOTSTRAP_PYTHON=%~1"
set "BOOTSTRAP_ARGS=%~2"
exit /b 0

:install_python
where winget >nul 2>nul
if not "%errorlevel%"=="0" exit /b 1
echo  No se encontro Python 3.11 o superior.
echo  Instalandolo una sola vez con el Administrador de paquetes de Windows...
echo  Puede tardar unos minutos. Si Windows pide permiso, acepta.
winget install --id Python.Python.3.13 --exact --silent --accept-package-agreements --accept-source-agreements
exit /b 0
