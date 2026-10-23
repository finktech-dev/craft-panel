"""Outbound HTTP helpers that keep downloads on known, HTTPS-only hosts.

Every request (including each redirect hop) is checked against an allow-list,
so a compromised API response or a redirect cannot point the panel at a local
service (SSRF) or at an unexpected host. Downloads are size-capped while they
stream and can be verified against the checksum published by the source.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Iterable
from pathlib import Path
from urllib.parse import urlsplit

import aiofiles
import httpx

_CHUNK = 64 * 1024

MODRINTH_HOSTS = frozenset({"api.modrinth.com", "cdn.modrinth.com"})
MOJANG_HOSTS = frozenset({
    "piston-meta.mojang.com",
    "piston-data.mojang.com",
    "launchermeta.mojang.com",
    "launcher.mojang.com",
})
FABRIC_HOSTS = frozenset({"meta.fabricmc.net", "maven.fabricmc.net"})
NEOFORGE_HOSTS = frozenset({"maven.neoforged.net"})
GITHUB_RELEASE_HOSTS = frozenset({
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})
ADOPTIUM_HOSTS = frozenset({"api.adoptium.net"}) | GITHUB_RELEASE_HOSTS
PLAYIT_HOSTS = frozenset({"api.playit.gg"}) | GITHUB_RELEASE_HOSTS
DISCORD_WEBHOOK_HOSTS = frozenset({"discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com"})


class UnsafeDownloadError(httpx.HTTPError):
    """Raised for disallowed hosts, oversized bodies or checksum mismatches."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


def is_allowed_url(url: str | httpx.URL, allowed_hosts: Iterable[str]) -> bool:
    parsed = urlsplit(str(url))
    host = (parsed.hostname or "").casefold().rstrip(".")
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
        and host in {candidate.casefold() for candidate in allowed_hosts}
    )


def allowed_client(
    allowed_hosts: Iterable[str],
    *,
    timeout: float,
    follow_redirects: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    """An AsyncClient that refuses any request outside ``allowed_hosts``."""
    hosts = frozenset(allowed_hosts)

    async def _check(request: httpx.Request) -> None:
        if not is_allowed_url(request.url, hosts):
            raise UnsafeDownloadError(f"Host no permitido: {request.url.host}")

    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=follow_redirects,
        max_redirects=5,
        event_hooks={"request": [_check]},
        transport=transport,
    )


async def download_to_file(
    client: httpx.AsyncClient,
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    expected_hash: tuple[str, str] | None = None,
) -> None:
    """Stream ``url`` to a temporary file, verify it and atomically move it.

    ``expected_hash`` is ``(algorithm, hexdigest)``, e.g. ``("sha512", "...")``.
    """
    digest = hashlib.new(expected_hash[0]) if expected_hash else None
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.download")
    written = 0
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise UnsafeDownloadError("La descarga supera el tamaño permitido.")
            async with aiofiles.open(temporary, "wb") as file:
                async for chunk in response.aiter_bytes(_CHUNK):
                    written += len(chunk)
                    if written > max_bytes:
                        raise UnsafeDownloadError("La descarga supera el tamaño permitido.")
                    if digest is not None:
                        digest.update(chunk)
                    await file.write(chunk)
        if expected_hash and digest is not None and digest.hexdigest().casefold() != expected_hash[1].casefold():
            raise UnsafeDownloadError("La suma de verificación de la descarga no coincide; se descartó.")
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
