<div align="center">

# Craft Panel

**Tu propio servidor de Minecraft con un doble clic. Sin comandos, sin abrir puertos, sin pelearte con Java.**

Un panel web gratis y de código abierto que instala, enciende y comparte un servidor de Minecraft desde una PC con Windows. Está hecho para que un chico, o cualquiera que no sea técnico, pueda armar un servidor privado para jugar con sus amigos.

[![Última versión](https://img.shields.io/github/v/release/finktech-dev/craft-panel?label=descargar&color=8abf58)](https://github.com/finktech-dev/craft-panel/releases/latest)
[![Tests](https://github.com/finktech-dev/craft-panel/actions/workflows/tests.yml/badge.svg)](https://github.com/finktech-dev/craft-panel/actions/workflows/tests.yml)
[![Windows 10 y 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078d4)](#compatibilidad)
[![Licencia MIT](https://img.shields.io/badge/licencia-MIT-blue)](LICENSE)

[**Descargar Craft Panel**](https://github.com/finktech-dev/craft-panel/releases/latest/download/CraftPanel.zip) · [Read in English](README.md) · [Guía del panel (en inglés)](docs/PANEL_GUIDE.md)

<img src="docs/images/demo.gif" alt="Craft Panel instalando un servidor, encendiéndolo, amigos entrando, la consola y una copia del mundo" width="880">

<sub>Grabado con el panel real en una instalación nueva de Windows: el servidor, los jugadores que entran y todas las pantallas son reales; no hay nada armado a mano. [Verlo como video](https://github.com/finktech-dev/craft-panel/releases/download/v1.0.0/craft-panel-demo.mp4).</sub>

</div>

## Qué hace

- **Te guía para armarlo:** elegís Minecraft normal, NeoForge o Fabric y la versión; el panel baja el servidor (y el Java que haga falta si el tuyo es viejo) y lo enciende.
- **Tus amigos entran desde sus casas** con [Playit.gg](https://playit.gg/) o una VPN como Tailscale, con la dirección lista para copiar. Sin tocar el router.
- **Mods de Modrinth** con un clic, con todo lo que necesitan, y un ZIP con los mismos mods para tus amigos.
- **Copias automáticas del mundo** que podés restaurar, descargar o guardar en otro disco.
- **Una consola que se entiende:** marca los errores de verdad, tiene modo chat, buscador y atajos de un clic.
- **Quién está jugando**, jugadores, mundos, reglas del juego, rangos (LuckPerms) y avisos en Discord, todo con palabras simples.
- **Te avisa cuando hay una versión nueva**, y actualizar nunca toca tus mundos.

| | |
| --- | --- |
| <img src="docs/images/dashboard.png" alt="Inicio: servidor encendido, tres amigos jugando y la dirección para compartir" width="420"> | <img src="docs/images/onboarding.png" alt="Primeros pasos: elegir Minecraft normal, con mods o Fabric" width="420"> |
| **Inicio:** si está encendido, quién juega y la dirección para tus amigos. | **Primeros pasos:** cuatro pasos cortos, sin escribir nada. |
| <img src="docs/images/mods-search.png" alt="Búsqueda de mods en Modrinth que funcionan con el servidor" width="420"> | <img src="docs/images/console.png" alt="Consola en vivo con el chat y los mensajes del servidor" width="420"> |
| **Mods:** solo los que funcionan con tu servidor, con lo que necesitan. | **Consola:** en vivo, con el chat y los errores a la vista. |
| <img src="docs/images/backups.png" alt="Copias del mundo con botones para volver a una copia y descargarla" width="420"> | <img src="docs/images/mods-installed.png" alt="Mods instalados con interruptores y el paquete para amigos" width="420"> |
| **Copias:** se hacen solas y volvés a una con un clic. | **Tus mods:** prendelos o apagalos y pasales el paquete a tus amigos. |

## Cómo empezar

Craft Panel funciona en **Windows 10 y Windows 11**. La primera vez necesita Internet.

**1. Bajá el panel y abrilo.**

1. Bajá **[CraftPanel.zip](https://github.com/finktech-dev/craft-panel/releases/latest/download/CraftPanel.zip)** de la [última versión](https://github.com/finktech-dev/craft-panel/releases/latest).
2. Hacé clic derecho en el ZIP y elegí **Extraer todo…**. Extraelo en una carpeta simple que OneDrive no sincronice, por ejemplo `C:\CraftPanel`. Evitá el Escritorio y Documentos si OneDrive los respalda.
3. Abrí la carpeta y hacé doble clic en **`iniciar_panel.bat`**. Si Windows avisa que el archivo viene de Internet, tocá **Más información** → **Ejecutar de todas formas** (o **Ejecutar**).

La primera vez tarda unos minutos: la ventana busca Python (o lo instala) y prepara el panel. Cuando está listo, se abre en el navegador. Dejá esa ventana negra abierta mientras usás el panel: si la cerrás, apretás Ctrl+C o cerrás sesión en Windows, el servidor se apaga guardando el mundo (para que siga encendido, desactivá `stop_with_panel`, mirá [el archivo de ajustes](docs/SERVER_FILE.md)). Guardá la contraseña que aparece en la primera pantalla.

**2. Instalá Playit para que tus amigos entren desde sus casas.**

Bajá la app para Windows de [playit.gg/download](https://playit.gg/download), instalala, abrí **Playit.gg** desde el menú Inicio e iniciá sesión. No hay que configurar nada más en el panel: se da cuenta solo. ¿Van a jugar todos en el mismo wifi? Salteá este paso.

**3. Seguí los pasos del panel.**

1. **Preparar:** si tu computadora ya tiene un Java que sirve, este paso se saltea. Si no, tocá **«Descargar Java»**.
2. **Elegir el juego:** Minecraft normal, con mods (NeoForge o Fabric) o un servidor que ya tengas.
3. **Amigos:** escribí los nombres de Minecraft de tus amigos. Con Playit abierto, tocá **«Usar la dirección de mi Playit»** (o pegá la dirección que te muestra Playit).
4. **Jugar:** tocá **«Encender»**. Cuando el servidor está listo, el panel te muestra la dirección para pasarles a tus amigos.

### Si algo sale mal

- **«Windows protegió su PC» o «Advertencia de seguridad»:** tocá **Más información** → **Ejecutar de todas formas**, o **Ejecutar**. Windows lo pregunta con los archivos bajados de Internet.
- **«Primero hay que descomprimir el ZIP»:** abriste el archivo desde adentro del ZIP. Extraelo primero (paso 1.2).
- **Escribir `python` abre la Microsoft Store o no encuentra Python:** el iniciador instala Python con el Administrador de paquetes de Windows cuando puede. Si igual falla, instalá Python 3.11 o más nuevo desde [python.org](https://www.python.org/downloads/) con **Add python.exe to PATH** marcado, y en Configuración de Windows buscá **Alias de ejecución de aplicaciones** y desactivá `python.exe` y `python3.exe`.
- **«Python se instaló, pero esta ventana todavía no lo encuentra»:** cerrá la ventana y volvé a abrir `iniciar_panel.bat`.
- **Desaparecen archivos o el panel falla dentro de OneDrive:** mové toda la carpeta a una que OneDrive no sincronice, como `C:\CraftPanel`.
- **Playit está instalado pero el panel dice que está apagado:** el servicio de Playit se enciende a mano. **«Encender»** lo enciende por vos, o abrí **Playit.gg** desde el menú Inicio.
- **El panel no encuentra tu dirección de Playit:** copiá la dirección que muestra la app de Playit o playit.gg y pegala en **«Pegá la dirección que te muestra Playit»**.
- **El navegador no se abrió:** abrí `http://127.0.0.1:8080` vos mientras la ventana negra está abierta.

### Actualizar

Cuando sale una versión nueva, el Inicio te avisa (lo podés desactivar con `check_updates = false` en [el archivo de ajustes](docs/SERVER_FILE.md)). Para actualizar:

1. Cerrá la ventana negra del panel: también guarda y apaga el servidor.
2. Bajá el **CraftPanel.zip** nuevo y extraelo.
3. Copiá todo lo de la carpeta nueva adentro de tu carpeta de Craft Panel y elegí **Reemplazar los archivos en el destino**.
4. Volvé a abrir `iniciar_panel.bat`.

Tus mundos, copias, mods y ajustes están en archivos que el ZIP no trae, así que quedan como estaban. Igual, hacer una copia antes de actualizar nunca está de más.

## Jugar con amigos

Playit.gg viene activado. Lo más fácil es la app oficial de Playit para Windows: el panel la detecta, nunca abre un segundo agente al lado y enciende su servicio cuando tocás **«Encender»**. **«Usar la dirección de mi Playit»** lee la dirección de Minecraft de la app, o la podés pegar vos.

**Por una VPN.** Si vos y tus amigos comparten una VPN (Tailscale, ZeroTier, Radmin VPN, Hamachi, NetBird o WireGuard), el panel la detecta sola y muestra la dirección del servidor en esa red. En **«Ajustes» → «Acceso por Internet» → «Por una VPN»** también podés abrir el panel a tus otros dispositivos de la VPN, para manejar el servidor desde el celular.

## Seguridad y tus datos

- El panel está pensado para usarse en esta computadora (`127.0.0.1`). No abras el puerto `8080` a Internet.
- No subas a ningún lado las claves de Playit, los webhooks de Discord, las contraseñas, los mundos, las copias ni los datos de los jugadores.
- Probá volver a una copia con un mundo de prueba antes de necesitarlo en serio. El proyecto puede tener errores y no reemplaza una copia en otro lugar.
- Leé [docs/SECURITY.md](docs/SECURITY.md) (en inglés) antes de abrir el panel fuera de esta computadora, y para avisar de un problema de seguridad.

## Compatibilidad

- **Probado:** Windows 10 y Windows 11, con Python 3.11 o más nuevo.
- **macOS y Linux:** no probados. `iniciar_panel.sh` existe y puede funcionar, pero nadie lo verifica antes de cada versión.
- **Servidores:** Vanilla, NeoForge y Fabric desde el asistente, o un servidor que ya tengas copiándolo en `server/`.

## Proyecto personal y abierto

Lo armé para mi propio servidor y lo comparto para que cualquiera lo use, lo adapte y lo mejore. Es un proyecto personal, no un servicio de hosting: puede tener errores. Hacé copias de tus mundos.

Este proyecto no está afiliado ni respaldado por Mojang Studios, Microsoft ni Minecraft.

## Cómo ayudar

¿Encontraste un error o tenés una idea? [Abrí un issue](https://github.com/finktech-dev/craft-panel/issues/new/choose) o preguntá en [Discussions](https://github.com/finktech-dev/craft-panel/discussions). Los pull requests son bienvenidos; leé la [guía para contribuir](docs/CONTRIBUTING.md) (en inglés). Si te sirve el panel, darle una ⭐ al repo ayuda a que lo encuentre más gente.

## Licencia

Publicado con la [licencia MIT](LICENSE).
