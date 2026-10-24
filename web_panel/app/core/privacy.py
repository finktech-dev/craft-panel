"""Keep the host's personal folders and players' IP addresses out of text the panel shows."""

from __future__ import annotations

import re

# "C:\Users\<name>\..." or "C:/Users/<name>/...": only the folder name is replaced, so the rest
# of the path stays useful for troubleshooting. A bare username is not touched on purpose:
# short names are ordinary words in game logs and replacing them would garble chat lines.
#
# Windows user names may contain spaces ("Alex Smith"): a name with spaces is only taken when a
# path separator follows it, otherwise the match stops at the first whitespace.
_USER_FOLDER = re.compile(
    r"(?i)\b([a-z]:[\\/]+users[\\/]+)"
    r"([^\\/\"'<>|:*?\r\n]+?(?=[\\/])|[^\\/\s\"'<>|:*?]+)"
)


def redact_personal_paths(text: str) -> str:
    """Replace the Windows user-folder name inside any path with ``<usuario>``."""
    if not text or "sers" not in text:  # cheap check before the regex ("Users"/"users")
        return text
    return _USER_FOLDER.sub(lambda match: f"{match.group(1)}<usuario>", text)


# Minecraft logs a connection as "/203.0.113.7:51234" (or an IPv6 form). Only addresses right after
# that slash are replaced, so version numbers such as "1.21.1" in the same line stay intact.
_CONNECTION_ADDRESS = re.compile(
    r"/(?:\d{1,3}(?:\.\d{1,3}){3}|\[[0-9A-Fa-f:.%\w]+\]|[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,}(?:%\w+)?)(?::\d{1,5})?"
)


def redact_ip_addresses(text: str) -> str:
    """Replace a player's connection address (``/IP:port``) with ``/<ip>``."""
    if not text or "/" not in text:
        return text
    return _CONNECTION_ADDRESS.sub("/<ip>", text)
