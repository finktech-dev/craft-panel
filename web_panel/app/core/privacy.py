"""Keep the host's personal folders out of text the panel shows (console, problem logs)."""

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
