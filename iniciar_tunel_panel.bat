@echo off
title Tunel Cloudflare - Panel Web Minecraft
echo ========================================================
echo   Iniciando Tunel Seguro Cloudflare (Quick Tunnel)
echo   Puerto local: http://localhost:8080
echo ========================================================
echo.
echo Preferido: crea el enlace desde Dashboard ^> Enlace HTTPS del panel.
echo Este script es una alternativa manual. No uses ambos a la vez.
echo.
echo Conectando con los servidores seguros de Cloudflare...
echo En unos segundos aparecera un enlace HTTPS (ej: https://...trycloudflare.com)
echo Copia ese enlace en el navegador de tu celular para entrar al panel desde cualquier lugar.
echo.
"%~dp0tools\cloudflared.exe" tunnel --url http://localhost:8080
pause
