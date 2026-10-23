@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Keep this file ASCII-only with CRLF line endings: cmd.exe parses it with
rem the OEM code page, so accented letters would print garbled.
title Restablecer contrasena - Panel Minecraft
set "PYTHON=%~dp0.venv\Scripts\python.exe"
echo.
echo Cierra primero la ventana de iniciar_panel.bat para reiniciar el bloqueo de intentos.
echo Esta herramienta solo modifica la contrasena local del panel.
echo.
if not exist "%PYTHON%" goto :missing_venv
rem Run from web_panel so the same .env file as iniciar_panel.bat is used.
cd /d "%~dp0web_panel"
"%PYTHON%" reset_admin_password.py
echo.
pause
exit /b 0

:missing_venv
echo [ERROR] Todavia no se preparo el panel en esta carpeta.
echo Abre primero iniciar_panel.bat una vez y despues vuelve a abrir este archivo.
echo.
pause
exit /b 1
