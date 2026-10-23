"""Regression tests for outbound downloads (SSRF allow-list, size caps, hashes) and uploads."""

from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import httpx
import pytest
from starlette.datastructures import Headers, UploadFile

from app.core.config import Settings
from app.core.net_safety import (
    MODRINTH_HOSTS,
    UnsafeDownloadError,
    allowed_client,
    download_to_file,
    is_allowed_url,
)
from app.services.mod_service import ModService, ModServiceError


class _StoppedServer:
    is_running = False


def _transport(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    "url",
    [
        "http://cdn.modrinth.com/a.jar",
        "https://127.0.0.1/a.jar",
        "https://cdn.modrinth.com.evil.example/a.jar",
        "https://user:pass@cdn.modrinth.com/a.jar",
        "https://cdn.modrinth.com:8443/a.jar",
        "file:///etc/passwd",
    ],
)
def test_is_allowed_url_rejects_non_allow_listed_urls(url: str) -> None:
    assert not is_allowed_url(url, MODRINTH_HOSTS)


def test_is_allowed_url_accepts_the_official_cdn() -> None:
    assert is_allowed_url("https://cdn.modrinth.com/data/x/versions/y/mod.jar", MODRINTH_HOSTS)


@pytest.mark.asyncio
async def test_redirect_to_a_local_service_is_refused(tmp_path: Path) -> None:
    transport = _transport({
        "https://cdn.modrinth.com/mod.jar": httpx.Response(302, headers={"location": "http://127.0.0.1:8080/api/x"}),
    })
    async with allowed_client(MODRINTH_HOSTS, timeout=5, transport=transport) as client:
        with pytest.raises(UnsafeDownloadError):
            await download_to_file(client, "https://cdn.modrinth.com/mod.jar", tmp_path / "mod.jar", max_bytes=1024)
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_download_enforces_size_and_checksum(tmp_path: Path) -> None:
    body = b"x" * 4096
    transport = _transport({"https://cdn.modrinth.com/mod.jar": httpx.Response(200, content=body)})
    async with allowed_client(MODRINTH_HOSTS, timeout=5, transport=transport) as client:
        with pytest.raises(UnsafeDownloadError):
            await download_to_file(client, "https://cdn.modrinth.com/mod.jar", tmp_path / "a.jar", max_bytes=1024)
        with pytest.raises(UnsafeDownloadError):
            await download_to_file(
                client, "https://cdn.modrinth.com/mod.jar", tmp_path / "b.jar",
                max_bytes=10_000, expected_hash=("sha512", "0" * 128),
            )
        good = hashlib.sha512(body).hexdigest()
        await download_to_file(
            client, "https://cdn.modrinth.com/mod.jar", tmp_path / "c.jar",
            max_bytes=10_000, expected_hash=("sha512", good),
        )
    assert sorted(path.name for path in tmp_path.iterdir()) == ["c.jar"]


@pytest.mark.asyncio
async def test_modrinth_ids_cannot_inject_api_paths(tmp_path: Path) -> None:
    service = ModService(configured_settings=Settings(project_root=tmp_path), manager=_StoppedServer())
    with pytest.raises(ModServiceError, match="identificador"):
        await service._get_compatible_version("../../users/me", None)


def _upload(name: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, headers=Headers({"content-type": "application/java-archive"}))


@pytest.mark.asyncio
async def test_mod_upload_rejects_non_zip_content(tmp_path: Path) -> None:
    service = ModService(configured_settings=Settings(project_root=tmp_path), manager=_StoppedServer())
    with pytest.raises(ModServiceError, match="válido"):
        await service.upload_mod(_upload("evil.jar", b"MZ\x90\x00 not a jar"))
    assert not list(service.mods_directory.iterdir())


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["a.jar:stream.jar", "CON.jar", "..\\x.jar", "evil .jar."])
async def test_mod_upload_rejects_unsafe_windows_names(tmp_path: Path, name: str) -> None:
    service = ModService(configured_settings=Settings(project_root=tmp_path), manager=_StoppedServer())
    with pytest.raises(ModServiceError):
        await service.upload_mod(_upload(name, b"PK\x03\x04"))


@pytest.mark.asyncio
async def test_mod_upload_accepts_a_real_jar(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
    service = ModService(configured_settings=Settings(project_root=tmp_path), manager=_StoppedServer())
    item = await service.upload_mod(_upload("good.jar", buffer.getvalue()))
    assert item.filename == "good.jar"
