"""Métricas no bloqueantes del proceso de Minecraft mediante psutil."""

from __future__ import annotations

import logging
import time

import psutil

from app.core.config import Settings, settings
from app.schemas.server import ServerMetrics
from app.services.server_process import MinecraftServerManager, server_manager

logger = logging.getLogger(__name__)
_MEBIBYTE = 1024 * 1024


class MetricsService:
    """Obtiene CPU, RSS y uptime sin esperar un intervalo de muestreo."""

    def __init__(
        self,
        manager: MinecraftServerManager = server_manager,
        configured_settings: Settings = settings,
    ) -> None:
        self._manager = manager
        self._settings = configured_settings

    def get_server_metrics(self) -> ServerMetrics:
        """Devuelve ceros si no hay proceso accesible, conservando el estado real."""
        state = str(self._manager.state)
        if not self._manager.is_running or self._manager.process_pid is None:
            return self._empty_metrics(state)

        try:
            process = self._get_java_process(self._manager.process_pid)
            memory_info = process.memory_info()
            ram_used_mb = round(memory_info.rss / _MEBIBYTE, 2)
            ram_total_mb = float(self._settings.allocated_ram_gb * 1024)
            return ServerMetrics(
                cpu_percent=round(max(process.cpu_percent(interval=None), 0.0), 2),
                ram_used_mb=ram_used_mb,
                ram_total_mb=ram_total_mb,
                ram_percent=round(min((ram_used_mb / ram_total_mb) * 100, 100.0), 2),
                uptime_seconds=max(int(time.time() - process.create_time()), 0),
                is_running=True,
                state=state,
                dev_mode=self._manager.dev_mode,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
            logger.warning("No se pudieron obtener métricas del proceso Minecraft: %s", error)
            return self._empty_metrics(state)

    @staticmethod
    def _get_java_process(root_pid: int) -> psutil.Process:
        root_process = psutil.Process(root_pid)
        for child in root_process.children(recursive=True):
            if child.name().lower() in {"java.exe", "javaw.exe", "java", "javaw"}:
                return child
        return root_process

    def _empty_metrics(self, state: str) -> ServerMetrics:
        return ServerMetrics(
            cpu_percent=0.0,
            ram_used_mb=0.0,
            ram_total_mb=float(self._settings.allocated_ram_gb * 1024),
            ram_percent=0.0,
            uptime_seconds=0,
            is_running=False,
            state=state,
            dev_mode=self._manager.dev_mode,
        )


metrics_service = MetricsService()
