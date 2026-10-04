"""Libro NBT de bienvenida que puede copiarse a la configuración del servidor."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path

import nbtlib
from nbtlib import Byte, Compound, List, String

from app.core.config import Settings, settings

logger = logging.getLogger(__name__)

_DEFAULT_TITLE = "Guía Inicial"
_DEFAULT_AUTHOR = "Servidor"
_DEFAULT_PAGES = [
    "§6§lGuía de Bienvenida\n\n§e¡Bienvenido al servidor! §fRespetá a otros jugadores y sus construcciones. Usá comandos de protección si están disponibles y consultá a los administradores si tenés dudas.",
    "§b§lConstrucción y Convivencia\n\n§fMantené el entorno limpio, no modifiques construcciones ajenas sin permiso y divertite jugando en comunidad.",
]


class BookService:
    def __init__(self, configured_settings: Settings = settings) -> None:
        self._settings = configured_settings

    @property
    def guide_book_path(self) -> Path:
        assert self._settings.defaultconfigs_directory is not None
        return self._settings.defaultconfigs_directory / "guia_inicial.nbt"

    @property
    def custom_guide_file(self) -> Path:
        base = Path(self._settings.panel_directory or ".")
        return base / ".guide_book.json"

    def _load_guide_content(self) -> tuple[str, str, list[str]]:
        cfg_file = self.custom_guide_file
        if cfg_file.is_file():
            try:
                data = json.loads(cfg_file.read_text(encoding="utf-8"))
                title = data.get("title", _DEFAULT_TITLE)
                author = data.get("author", _DEFAULT_AUTHOR)
                pages = data.get("pages", _DEFAULT_PAGES)
                if isinstance(pages, list) and pages:
                    return str(title), str(author), [str(p) for p in pages]
            except Exception as error:
                logger.warning("Error al leer .guide_book.json: %s", error)
        return _DEFAULT_TITLE, _DEFAULT_AUTHOR, _DEFAULT_PAGES

    def generate_guide_book(self) -> Path:
        """Escribe un item stack con el componente moderno de libro escrito."""
        self.guide_book_path.parent.mkdir(parents=True, exist_ok=True)
        title, author, pages = self._load_guide_content()
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
                                        "title": String(title),
                                        "author": String(author),
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

