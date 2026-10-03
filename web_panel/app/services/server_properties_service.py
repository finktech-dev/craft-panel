"""Servicio para lectura, modificación y documentación con tooltips de server.properties."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.services.runtime_guard import require_server_stopped
from app.services.server_process import MinecraftServerManager, server_manager
from app.schemas.worlds import (
    ServerPropertiesResponse,
    ServerPropertyDefinition,
    ServerPropertyOption,
)

_PROPERTY_METADATA: dict[str, dict[str, Any]] = {
    # 🎮 Jugabilidad y Dificultad
    "difficulty": {
        "label": "Dificultad del juego",
        "category": "Jugabilidad y Dificultad",
        "type": "select",
        "default": "easy",
        "recommended": "normal o hard",
        "description": "Define la dificultad de los combates, el daño recibido por los monstruos de mods (Cataclysm, Mowzie's Mobs) y el impacto del hambre en la salud.",
        "impact": "En 'peaceful' los jefes y monstruos agresivos desaparecen inmediatamente.",
        "options": [
            {"value": "peaceful", "label": "Pacífico (Sin enemigos ni hambre)"},
            {"value": "easy", "label": "Fácil (Enemigos débiles)"},
            {"value": "normal", "label": "Normal (Recomendado para aventuras equilibradas)"},
            {"value": "hard", "label": "Difícil (Máximo desafío para jefes y armas)"},
        ],
    },
    "gamemode": {
        "label": "Modo de juego predeterminado",
        "category": "Jugabilidad y Dificultad",
        "type": "select",
        "default": "survival",
        "recommended": "survival",
        "description": "Modo en el que ingresan los nuevos jugadores que se unen por primera vez al servidor.",
        "impact": "Si 'force-gamemode' está activo, cambiará a todos los jugadores a este modo en cada conexión.",
        "options": [
            {"value": "survival", "label": "Supervivencia (Survival estándar)"},
            {"value": "creative", "label": "Creativo (Recursos y vuelo infinitos)"},
            {"value": "adventure", "label": "Aventura (Sin romper bloques sin herramientas)"},
            {"value": "spectator", "label": "Espectador (Incorpóreo e invisible)"},
        ],
    },
    "force-gamemode": {
        "label": "Forzar modo de juego al entrar",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "false",
        "recommended": "false",
        "description": "Si está activo, obliga a todos los jugadores a volver al modo predeterminado cada vez que inician sesión.",
        "impact": "Evita que administradores o jugadores conserven el modo creativo tras desconectarse.",
    },
    "hardcore": {
        "label": "Modo Extremo (Hardcore)",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "false",
        "recommended": "false",
        "description": "Al morir, el jugador no puede reaparecer y queda permanentemente bloqueado en modo espectador.",
        "impact": "Fija la dificultad en Difícil de forma forzada.",
    },
    "pvp": {
        "label": "Daño entre jugadores (PVP)",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "true",
        "recommended": "true",
        "description": "Permite que los jugadores se hagan daño con ataques cuerpo a cuerpo, flechas o proyectiles de Point Blank.",
        "impact": "Si está desactivado, protege a los jugadores de ataques accidentales o fuego amigo.",
    },
    "allow-flight": {
        "label": "Permitir vuelo / propulsión",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "false",
        "recommended": "true (con mods de mochilas o planeadores)",
        "description": "Evita que el servidor expulse automáticamente a jugadores que usen mochilas propulsoras, planeadores, trenes rápidos o ítems mágicos por sospecha de 'hack de vuelo'.",
        "impact": "Muy recomendado poner en 'true' en modpacks para evitar expulsiones falsas.",
    },
    "spawn-monsters": {
        "label": "Generación de monstruos agresivos",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "true",
        "recommended": "true",
        "description": "Controla si aparecen zombis, esqueletos y criaturas de mods durante la noche o en zonas oscuras.",
        "impact": "Desactivarlo vacía mazmorras y biomas de criaturas hostiles.",
    },
    "spawn-animals": {
        "label": "Generación de animales pasivos",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "true",
        "recommended": "true",
        "description": "Permite que vacas, ovejas, caballos y fauna de biomas se generen de forma natural.",
        "impact": "Si se apaga, no nacerán nuevos animales en el mundo.",
    },
    "spawn-npcs": {
        "label": "Generación de aldeanos y comerciantes",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "true",
        "recommended": "true",
        "description": "Permite que aparezcan aldeanos en las aldeas y comerciantes ambulantes con sus llamas.",
        "impact": "Esencial para el comercio de esmeraldas y libros de encantamientos.",
    },
    "enable-command-block": {
        "label": "Habilitar Bloques de Comandos",
        "category": "Jugabilidad y Dificultad",
        "type": "boolean",
        "default": "false",
        "recommended": "false (o true si hacés mapas de aventura)",
        "description": "Permite la ejecución de bloques de comandos colocados por administradores.",
        "impact": "Por seguridad se deja en false a menos que uses mecánicas con bloques de comandos.",
    },

    # 🚀 Rendimiento y Chunks
    "view-distance": {
        "label": "Distancia de visión (View Distance)",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "6",
        "recommended": "6 a 8",
        "min": 3,
        "max": 32,
        "description": "Radio en chunks (16x16 bloques) que el servidor envía a la pantalla de cada jugador.",
        "impact": "ALTO IMPACTO EN RAM Y CPU. Cada incremento al cuadrado aumenta drásticamente el consumo del procesador.",
    },
    "simulation-distance": {
        "label": "Distancia de simulación",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "4",
        "recommended": "4 a 6",
        "min": 3,
        "max": 32,
        "description": "Radio en chunks alrededor del jugador donde el servidor procesa entidades, cultivos, hornos, mecanismos de Create y granjas.",
        "impact": "CRÍTICO PARA LOS TPS (Lag de servidor). Mantener entre 4 y 5 garantiza 20 TPS estables en modpacks pesados.",
    },
    "max-players": {
        "label": "Límite máximo de jugadores",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "20",
        "recommended": "10 a 20",
        "min": 1,
        "max": 100,
        "description": "Cantidad simultánea máxima de jugadores que pueden ingresar al servidor al mismo tiempo.",
        "impact": "Jugadores con OP o permiso de bypass pueden ingresar superando este límite.",
    },
    "sync-chunk-writes": {
        "label": "Escritura síncrona de chunks a disco",
        "category": "Rendimiento y Chunks",
        "type": "boolean",
        "default": "true",
        "recommended": "true",
        "description": "Guarda los chunks inmediatamente en disco para prevenir corrupción de archivos si la PC se apaga bruscamente.",
        "impact": "Mantiene el mundo protegido de corrupciones en cortes de luz o cierres forzados.",
    },
    "entity-broadcast-range-percentage": {
        "label": "Rango de sincronización de entidades (%)",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "100",
        "recommended": "80 a 100",
        "min": 10,
        "max": 500,
        "description": "Porcentaje de distancia a la que el servidor transmite datos de movimiento de monstruos, animales y proyectiles.",
        "impact": "Bajarlo al 70-80% alivia significativamente el tráfico de red y lag si hay muchas entidades.",
    },
    "max-tick-time": {
        "label": "Límite de tiempo por tick (Watchdog ms)",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "60000",
        "recommended": "60000",
        "min": -1,
        "max": 600000,
        "description": "Tiempo máximo en milisegundos que un tick del servidor puede tardar antes de que el perro guardián (Watchdog) fuerce el apagado.",
        "impact": "Dejarlo en -1 oculta cuelgues prolongados y dificulta la recuperación automática. Investigá los picos con Spark en vez de desactivar el watchdog.",
    },
    "network-compression-threshold": {
        "label": "Umbral de compresión de red (Bytes)",
        "category": "Rendimiento y Chunks",
        "type": "number",
        "default": "256",
        "recommended": "256",
        "min": -1,
        "max": 1024,
        "description": "Tamaño de paquete a partir del cual el servidor comprime los datos enviados al cliente.",
        "impact": "256 es el estándar de Minecraft. Ahorra ancho de banda en conexiones residenciales.",
    },

    # 🛡️ Seguridad y Red
    "online-mode": {
        "label": "Modo Online (Verificación Mojang/Microsoft)",
        "category": "Seguridad y Red",
        "type": "boolean",
        "default": "false",
        "recommended": "false (para permitir jugadores No-Premium)",
        "description": "Si está en 'true', solo cuentas premium oficiales de Minecraft pueden ingresar. Si está en 'false', permite el ingreso de amigos con launchers libres (TLauncher, Feather, etc.).",
        "impact": "En false es indispensable para comunidades mixtas de amigos.",
    },
    "white-list": {
        "label": "Lista Blanca (Whitelist)",
        "category": "Seguridad y Red",
        "type": "boolean",
        "default": "false",
        "recommended": "true para este servidor privado",
        "description": "Restringe el acceso al servidor únicamente a los jugadores agregados en la lista blanca.",
        "impact": "Si está activa, ningún jugador no autorizado podrá unirse aunque conozca la IP.",
    },
    "enforce-whitelist": {
        "label": "Expulsión estricta de Whitelist",
        "category": "Seguridad y Red",
        "type": "boolean",
        "default": "false",
        "recommended": "true junto con white-list=true",
        "description": "Si se activa, expulsa inmediatamente a cualquier jugador conectado si su nombre es removido de la lista blanca.",
        "impact": "Asegura que los cambios en la lista blanca surtan efecto en el momento.",
    },
    "spawn-protection": {
        "label": "Radio de protección del Spawn (Bloques)",
        "category": "Seguridad y Red",
        "type": "number",
        "default": "32",
        "recommended": "0 a 16",
        "min": 0,
        "max": 128,
        "description": "Radio en bloques alrededor del punto de aparición donde los jugadores que NO son operadores (OP) no pueden romper ni colocar bloques.",
        "impact": "Poner 0 permite que cualquiera construya o modifique cerca del punto de spawn inicial.",
    },
    "hide-online-players": {
        "label": "Ocultar lista de jugadores conectados",
        "category": "Seguridad y Red",
        "type": "boolean",
        "default": "false",
        "recommended": "false",
        "description": "Oculta los nombres y cabezas de los jugadores cuando alguien pasa el cursor sobre el contador de jugadores en el menú multijugador.",
        "impact": "Aumenta la privacidad si no deseás mostrar quién está jugando.",
    },
    "prevent-proxy-connections": {
        "label": "Bloquear proxies y VPNs",
        "category": "Seguridad y Red",
        "type": "boolean",
        "default": "false",
        "recommended": "false",
        "description": "Verifica con los servidores de Mojang si la IP entrante proviene de un túnel o proxy comercial.",
        "impact": "Debe estar en false para evitar problemas con túneles como Playit o Cloudflare.",
    },
    "server-port": {
        "label": "Puerto TCP/UDP del servidor",
        "category": "Seguridad y Red",
        "type": "number",
        "default": "25565",
        "recommended": "25565",
        "min": 1024,
        "max": 65535,
        "description": "Puerto de red donde escucha el servidor local de Minecraft.",
        "impact": "Debe coincidir con el puerto configurado en el túnel Playit (por defecto 25565).",
    },

    # 🎨 Mensaje y Apariencia
    "motd": {
        "label": "Mensaje del Día (MOTD)",
        "category": "Mensaje y Apariencia",
        "type": "text",
        "default": "A Minecraft Server",
        "recommended": "Tu propio mensaje con colores (§a, §6, §l, etc.)",
        "description": "Texto descriptivo de dos líneas que se muestra en la lista multijugador de Minecraft.",
        "impact": "Soporta códigos de formato de Minecraft: §0 a §f para colores, §l para negrita, §o para cursiva.",
    },
}

_MC_COLOR_MAP = {
    "§0": "#000000",
    "§1": "#0000AA",
    "§2": "#00AA00",
    "§3": "#00AAAA",
    "§4": "#AA0000",
    "§5": "#AA00AA",
    "§6": "#FFAA00",
    "§7": "#AAAAAA",
    "§8": "#555555",
    "§9": "#5555FF",
    "§a": "#55FF55",
    "§b": "#55FFFF",
    "§c": "#FF5555",
    "§d": "#FF55FF",
    "§e": "#FFFF55",
    "§f": "#FFFFFF",
}


def motd_to_html(motd: str) -> str:
    """Convierte códigos de color § de Minecraft a HTML seguro para preview."""
    import html

    cleaned = html.escape(motd)
    pattern = re.compile(r"§([0-9a-fk-or])", re.I)
    
    parts = []
    current_color = "#FFFFFF"
    is_bold = False
    is_italic = False
    
    last_idx = 0
    for match in pattern.finditer(cleaned):
        text_before = cleaned[last_idx:match.start()]
        if text_before:
            styles = [f"color:{current_color}"]
            if is_bold:
                styles.append("font-weight:bold")
            if is_italic:
                styles.append("font-style:italic")
            parts.append(f'<span style="{";".join(styles)}">{text_before}</span>')
        
        code = match.group(1).lower()
        if code in "0123456789abcdef":
            current_color = _MC_COLOR_MAP.get(f"§{code}", "#FFFFFF")
        elif code == "l":
            is_bold = True
        elif code == "o":
            is_italic = True
        elif code == "r":
            current_color = "#FFFFFF"
            is_bold = False
            is_italic = False
            
        last_idx = match.end()
        
    remaining = cleaned[last_idx:]
    if remaining:
        styles = [f"color:{current_color}"]
        if is_bold:
            styles.append("font-weight:bold")
        if is_italic:
            styles.append("font-style:italic")
        parts.append(f'<span style="{";".join(styles)}">{remaining}</span>')
        
    html_output = "".join(parts) if parts else cleaned
    return html_output.replace(r"\n", "<br>")


class ServerPropertiesService:
    def __init__(
        self,
        configured_settings: Settings = settings,
        manager: MinecraftServerManager = server_manager,
    ) -> None:
        self._settings = configured_settings
        self._manager = manager
        self._lock = asyncio.Lock()

    @property
    def file_path(self) -> Path:
        assert self._settings.server_directory
        return self._settings.server_directory / "server.properties"

    def read_properties(self) -> dict[str, str]:
        if not self.file_path.is_file():
            return {}
        result: dict[str, str] = {}
        for line in self.file_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                result[key.strip()] = val.strip()
        return result

    async def get_properties_response(self) -> ServerPropertiesResponse:
        current_props = await asyncio.to_thread(self.read_properties)
        
        definitions: list[ServerPropertyDefinition] = []
        categories: list[str] = [
            "Jugabilidad y Dificultad",
            "Rendimiento y Chunks",
            "Seguridad y Red",
            "Mensaje y Apariencia",
            "Otras opciones avanzadas",
        ]

        # Primero agregamos las propiedades documentadas con metadatos
        for key, meta in _PROPERTY_METADATA.items():
            curr_val = current_props.get(key, meta.get("default", ""))
            opts = None
            if "options" in meta:
                opts = [
                    ServerPropertyOption(
                        value=o["value"],
                        label=o["label"],
                        description=o.get("description"),
                    )
                    for o in meta["options"]
                ]
            
            definitions.append(
                ServerPropertyDefinition(
                    key=key,
                    label=meta["label"],
                    category=meta["category"],
                    type=meta["type"],
                    current_value=curr_val,
                    default_value=meta.get("default", ""),
                    description=meta["description"],
                    recommended_value=meta.get("recommended", ""),
                    impact=meta.get("impact", ""),
                    options=opts,
                    min_value=meta.get("min"),
                    max_value=meta.get("max"),
                )
            )

        # Agregamos las propiedades restantes que existan en el archivo
        for key, val in current_props.items():
            if key in _PROPERTY_METADATA:
                continue
            # Tipo automático
            val_lower = val.lower()
            val_type = "boolean" if val_lower in {"true", "false"} else "number" if val.lstrip("-").isdigit() else "text"
            definitions.append(
                ServerPropertyDefinition(
                    key=key,
                    label=key.replace("-", " ").title(),
                    category="Otras opciones avanzadas",
                    type=val_type,
                    current_value=val,
                    default_value=val,
                    description=f"Ajuste interno estándar de Minecraft ({key}).",
                    recommended_value="Conservar valor por defecto a menos que se requiera un cambio específico.",
                    impact="Modifica el comportamiento interno de red o arranque de Minecraft.",
                )
            )

        raw_motd = current_props.get("motd", "§6Servidor Minecraft")
        preview = motd_to_html(raw_motd)

        return ServerPropertiesResponse(
            categories=categories,
            properties=definitions,
            raw_motd=raw_motd,
            motd_preview_html=preview,
        )

    async def update_properties(self, updates: dict[str, str]) -> ServerPropertiesResponse:
        require_server_stopped(self._manager, "modificar server.properties")
        async with self._lock:
            await asyncio.to_thread(self._write_updates, updates)
        return await self.get_properties_response()

    def _write_updates(self, updates: dict[str, str]) -> None:
        if not self.file_path.is_file():
            # Crear desde cero si no existiera
            lines = [f"{k}={v}" for k, v in updates.items()]
            self.file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return

        original_lines = self.file_path.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines: list[str] = []
        updated_keys = set(updates.keys())
        written_keys = set()

        for line in original_lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                new_lines.append(line)
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key in updated_keys:
                    new_lines.append(f"{key}={updates[key]}")
                    written_keys.add(key)
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)

        # Agregar claves nuevas que no estaban en el archivo original
        for key, val in updates.items():
            if key not in written_keys:
                new_lines.append(f"{key}={val}")

        tmp = self.file_path.with_name(f".server.properties.{uuid.uuid4().hex}.tmp")
        tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.replace(tmp, self.file_path)


server_properties_service = ServerPropertiesService()
