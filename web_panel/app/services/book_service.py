"""Libro NBT de bienvenida que puede copiarse a la configuración del servidor."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import nbtlib
from nbtlib import Byte, Compound, List, String

from app.core.config import Settings, settings


class BookService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings

    @property
    def guide_book_path(self) -> Path:
        assert self._settings.defaultconfigs_directory is not None
        return self._settings.defaultconfigs_directory / "guia_inicial.nbt"

    def generate_guide_book(self) -> Path:
        """Escribe un item stack 1.21.1 con el componente moderno de libro escrito."""
        self.guide_book_path.parent.mkdir(parents=True, exist_ok=True)
        pages = [
            "§6§lManual del Maquinista y Soldado\n\n§eBienvenido al Reino. §fRespetá a otros jugadores y sus construcciones. Usá §b/claim §fpara proteger tu base y pedí ayuda antes de modificar terrenos ajenos.",
            "§b§lLocomotoras de vapor\n\n§fArmá la vía con Create, conectá bogeys y una caldera. Desde la estación, programá horarios y destinos; frená siempre antes de cambiar una aguja.",
            "§e§lArmas históricas\n\n§fLas armas de cerrojo requieren munición compatible. Apuntá con miras de hierro, dispará con calma y compensá el retroceso. Nunca pruebes armas dentro de zonas protegidas.",
        ]
        root = Compound(
            {
                "Item": Compound(
                    {
                        "id": String("minecraft:written_book"),
                        "count": Byte(1),
                        "components": Compound(
                            {
                                "minecraft:written_book_content": Compound(
                                    {
                                        "title": String("Manual del Maquinista y Soldado"),
                                        "author": String("El Reino"),
                                        "pages": List[String]([String(page) for page in pages]),
                                    }
                                )
                            }
                        ),
                    }
                )
            }
        )
        temporary = self.guide_book_path.with_name(f".{self.guide_book_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            nbtlib.File(root, gzipped=True).save(temporary)
            os.replace(temporary, self.guide_book_path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return self.guide_book_path


book_service = BookService()
