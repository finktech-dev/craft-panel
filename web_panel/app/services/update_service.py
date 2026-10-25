"""Tells the owner when a newer Craft Panel release is published on GitHub.

The check reads the public "latest release" of the panel's repository at most
once a day. Nothing about this PC or its server is sent, and any network or
GitHub error simply means "no notice": the panel never depends on it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.core.net_safety import allowed_client

logger = logging.getLogger(__name__)

VERSION_FILE = Path(__file__).resolve().parents[3] / "VERSION"
GITHUB_API_HOSTS = frozenset({"api.github.com"})
CHECK_EVERY_SECONDS = 24 * 3600
RETRY_AFTER_ERROR_SECONDS = 3600
_VERSION = re.compile(r"^v?(\d{1,4})\.(\d{1,4})\.(\d{1,4})$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """``1.2.3`` or ``v1.2.3`` as a comparable tuple; anything else (pre-releases too) is ignored."""
    match = _VERSION.match((text or "").strip())
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def current_version(path: Path = VERSION_FILE) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text if parse_version(text) else "0.0.0"


@dataclass(frozen=True, slots=True)
class UpdateStatus:
    current: str
    enabled: bool
    latest: str | None = None
    available: bool = False
    url: str | None = None


class UpdateService:
    def __init__(
        self,
        repository: str = "finktech-dev/craft-panel",
        *,
        version_file: Path = VERSION_FILE,
        transport: httpx.AsyncBaseTransport | None = None,
        clock=time.monotonic,
    ) -> None:
        if not _REPOSITORY.match(repository):
            raise ValueError("update repository must look like owner/name")
        self._repository = repository
        self._version_file = version_file
        self._transport = transport
        self._clock = clock
        self._lock = asyncio.Lock()
        self._latest: tuple[str, str] | None = None
        self._next_check = 0.0

    @property
    def releases_page(self) -> str:
        return f"https://github.com/{self._repository}/releases"

    async def status(self, *, enabled: bool) -> UpdateStatus:
        current = current_version(self._version_file)
        if not enabled:
            return UpdateStatus(current=current, enabled=False)
        async with self._lock:
            if self._clock() >= self._next_check:
                await self._refresh()
        if self._latest is None:
            return UpdateStatus(current=current, enabled=True)
        latest, url = self._latest
        newer = (parse_version(latest) or (0, 0, 0)) > (parse_version(current) or (0, 0, 0))
        return UpdateStatus(current=current, enabled=True, latest=latest, available=newer, url=url)

    async def _refresh(self) -> None:
        try:
            async with allowed_client(GITHUB_API_HOSTS, timeout=10, follow_redirects=False, transport=self._transport) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{self._repository}/releases/latest",
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "craft-panel-update-check"},
                )
            if response.status_code == 404:
                # No release published yet.
                self._latest = None
            else:
                response.raise_for_status()
                self._latest = self._read_release(response.json())
            self._next_check = self._clock() + CHECK_EVERY_SECONDS
        except (httpx.HTTPError, ValueError) as error:
            logger.info("Could not check for a newer panel version: %s", error)
            self._next_check = self._clock() + RETRY_AFTER_ERROR_SECONDS

    def _read_release(self, data: Any) -> tuple[str, str] | None:
        if not isinstance(data, dict) or data.get("draft") or data.get("prerelease"):
            return None
        tag = str(data.get("tag_name") or "")
        version = parse_version(tag)
        if version is None:
            return None
        # Only ever link to this repository's own release page.
        url = str(data.get("html_url") or "")
        if not url.startswith(f"{self.releases_page}/"):
            url = f"{self.releases_page}/tag/{tag}"
        return ".".join(map(str, version)), url


update_service = UpdateService()
