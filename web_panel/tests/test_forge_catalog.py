"""Forge version catalog parsing (maven metadata + promotions)."""

from app.services.installer_service import InstallerService
from app.services.server_version_service import forge_to_minecraft
from app.services.version_catalog_service import (
    forge_catalog_entries,
    parse_forge_metadata,
    parse_forge_promotions,
)

_METADATA = """<metadata>
  <versioning><versions>
    <version>1.20.1-47.4.0</version>
    <version>1.20.1-47.4.28</version>
    <version>1.21.1-52.1.20</version>
    <version>1.12.2-14.23.5.2859</version>
    <version>1.7.10_pre4</version>
    <version>1.12.2-14.23.4.2720-4627</version>
  </versions></versioning>
</metadata>"""

_PROMOS = {
    "promos": {
        "1.20.1-recommended": "47.4.28",
        "1.20.1-latest": "47.4.29",
        "1.21.1-recommended": "52.1.20",
        "1.12.2-recommended": "14.23.5.2859",
    }
}


def test_forge_to_minecraft():
    assert forge_to_minecraft("1.20.1-47.4.0") == "1.20.1"
    assert forge_to_minecraft("1.12.2-14.23.5.2859") == "1.12.2"
    assert forge_to_minecraft("not-a-build") is None


def test_parse_forge_metadata_keeps_only_clean_builds_newest_first():
    grouped = parse_forge_metadata(_METADATA)
    # Branch-suffixed and pre-release builds are dropped.
    assert "1.7.10" not in grouped
    assert grouped["1.12.2"] == ["1.12.2-14.23.5.2859"]
    assert grouped["1.20.1"] == ["1.20.1-47.4.28", "1.20.1-47.4.0"]  # newest first


def test_parse_forge_promotions():
    promos = parse_forge_promotions(_PROMOS)
    assert promos["1.20.1"]["recommended"] == "1.20.1-47.4.28"
    assert promos["1.20.1"]["latest"] == "1.20.1-47.4.29"
    assert promos["1.21.1"]["recommended"] == "1.21.1-52.1.20"


def test_forge_catalog_entries_prefers_recommended():
    grouped = parse_forge_metadata(_METADATA)
    promos = parse_forge_promotions(_PROMOS)
    entries = {e.minecraft_version: e for e in forge_catalog_entries(grouped, promos)}
    assert entries["1.20.1"].loader_version == "1.20.1-47.4.28"
    assert entries["1.20.1"].stable is True
    assert entries["1.12.2"].loader_version == "1.12.2-14.23.5.2859"


def test_forge_installer_url():
    url = InstallerService.forge_installer_url("1.20.1-47.4.28")
    assert url == "https://maven.minecraftforge.net/net/minecraftforge/forge/1.20.1-47.4.28/forge-1.20.1-47.4.28-installer.jar"
