@echo off
title Restablecer contrasena - Panel Minecraft
echo.
echo Cerrá primero iniciar_panel.bat para reiniciar el bloqueo de intentos.
echo Esta herramienta solo modifica la contrasena local del panel.
echo Si no escribis ninguna, se genera una nueva y se muestra una sola vez en esta ventana.
echo.
"%~dp0.venv\Scripts\python.exe" "%~dp0web_panel\reset_admin_password.py"
echo.
pause
