@echo off
title Tunel Cloudflare - Panel Web Minecraft
echo ========================================================
echo   Iniciando Tunel Seguro Cloudflare (Quick Tunnel)
echo   Puerto local: http://localhost:8080
echo ========================================================
echo.
echo Crea un enlace HTTPS temporal para entrar al panel desde afuera de tu casa.
echo Cerra esta ventana cuando termines: el enlace deja de funcionar.
set "CF_BIN=%~dp0tools\cloudflared.exe"
if not exist "%CF_BIN%" (
  where cloudflared >nul 2>nul
  if not errorlevel 1 (
    set "CF_BIN=cloudflared"
  ) else (
    echo [AVISO] No se encontro cloudflared.exe en tools\ ni en el sistema.
        echo O descarga cloudflared desde https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    echo y colocalo en la carpeta tools\
    echo.
    pause
    exit /b 1
  )
)

echo Conectando con los servidores seguros de Cloudflare...
echo En unos segundos aparecera un enlace HTTPS (ej: https://...trycloudflare.com)
echo Copia ese enlace en el navegador de tu celular para entrar al panel desde cualquier lugar.
echo.
"%CF_BIN%" tunnel --url http://localhost:8080
pause
