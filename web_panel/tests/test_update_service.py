"""The dashboard's "new panel version" notice: what GitHub answers and how often it is asked."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.services.update_service import VERSION_FILE, UpdateService, current_version, parse_version

LATEST = "https://api.github.com/repos/finktech-dev/craft-panel/releases/latest"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_service(tmp_path: Path, answer, version: str = "1.0.0") -> tuple[UpdateService, list[httpx.Request], Clock]:
    (tmp_path / "VERSION").write_text(f"{version}\n", encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer(request)

    clock = Clock()
    service = UpdateService(version_file=tmp_path / "VERSION", transport=httpx.MockTransport(handler), clock=clock)
    return service, requests, clock


def release(tag: str, **extra) -> httpx.Response:
    return httpx.Response(200, json={"tag_name": tag, "html_url": f"https://github.com/finktech-dev/craft-panel/releases/tag/{tag}", **extra})


def test_the_repository_version_is_a_plain_release_number() -> None:
    assert parse_version(current_version(VERSION_FILE)) is not None


@pytest.mark.asyncio
async def test_a_newer_release_is_announced_with_its_page(tmp_path: Path) -> None:
    service, requests, _ = make_service(tmp_path, lambda _: release("v1.2.0"))
    status = await service.status(enabled=True)
    assert status.available and status.latest == "1.2.0" and status.current == "1.0.0"
    assert status.url == "https://github.com/finktech-dev/craft-panel/releases/tag/v1.2.0"
    assert str(requests[0].url) == LATEST


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["v1.0.0", "v0.9.9", "v2.0.0-beta.1", "nightly"])
async def test_no_notice_for_the_same_an_older_or_an_unusual_release(tmp_path: Path, tag: str) -> None:
    service, _, _ = make_service(tmp_path, lambda _: release(tag))
    assert not (await service.status(enabled=True)).available


@pytest.mark.asyncio
async def test_prereleases_and_foreign_links_are_ignored(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path, lambda _: release("v9.0.0", prerelease=True))
    assert not (await service.status(enabled=True)).available

    def foreign(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tag_name": "v1.1.0", "html_url": "https://example.com/fake"})

    service, _, _ = make_service(tmp_path, foreign)
    status = await service.status(enabled=True)
    assert status.url == "https://github.com/finktech-dev/craft-panel/releases/tag/v1.1.0"


@pytest.mark.asyncio
async def test_github_is_asked_once_a_day(tmp_path: Path) -> None:
    service, requests, clock = make_service(tmp_path, lambda _: release("v1.1.0"))
    await service.status(enabled=True)
    clock.now += 23 * 3600
    await service.status(enabled=True)
    assert len(requests) == 1
    clock.now += 3600
    await service.status(enabled=True)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_no_release_yet_or_an_error_means_no_notice(tmp_path: Path) -> None:
    service, _, _ = make_service(tmp_path, lambda _: httpx.Response(404))
    assert (await service.status(enabled=True)).latest is None

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    service, requests, clock = make_service(tmp_path, offline)
    status = await service.status(enabled=True)
    assert not status.available and status.latest is None
    # An error is retried after an hour, not on every page load.
    await service.status(enabled=True)
    assert len(requests) == 1
    clock.now += 3600
    await service.status(enabled=True)
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_turned_off_it_never_asks(tmp_path: Path) -> None:
    service, requests, _ = make_service(tmp_path, lambda _: release("v5.0.0"))
    status = await service.status(enabled=False)
    assert not status.enabled and not status.available
    assert requests == []


def test_a_missing_or_odd_version_file_counts_as_unknown(tmp_path: Path) -> None:
    assert current_version(tmp_path / "missing") == "0.0.0"
    (tmp_path / "VERSION").write_text("dev build", encoding="utf-8")
    assert current_version(tmp_path / "VERSION") == "0.0.0"
