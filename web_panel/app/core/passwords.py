"""Hashing and verification of the administrator password.

Stored format (a single ASCII string, safe to keep in JSON)::

    scrypt$<log2 N>$<r>$<p>$<salt, urlsafe base64>$<key, urlsafe base64>

The cost parameters travel with each hash, so they can be raised later
without breaking passwords that were stored with the previous values.
This module must not import ``app.core.config``: the settings use it while
they are being built.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from typing import Final

SCHEME: Final = "scrypt"
# N = 2**15, r = 8, p = 1 needs 32 MiB and takes roughly 0.1 s on a desktop
# CPU: expensive for an offline guesser, cheap enough for a rate-limited login.
DEFAULT_LOG2_N: Final = 15
DEFAULT_R: Final = 8
DEFAULT_P: Final = 1
_SALT_BYTES: Final = 16
_KEY_BYTES: Final = 32
# Bounds for parameters read back from disk, so a corrupted or tampered file
# cannot make every login allocate gigabytes.
_MAX_LOG2_N: Final = 20
_MAX_R: Final = 16
_MAX_P: Final = 4


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, log2_n: int, r: int, p: int) -> bytes:
    n = 1 << log2_n
    # scrypt needs 128 * r * N bytes (plus a little); give it room explicitly.
    maxmem = 128 * r * n * p + 16 * 1024 * 1024
    return hashlib.scrypt(password.encode("utf-8", "surrogatepass"), salt=salt, n=n, r=r, p=p, maxmem=maxmem, dklen=_KEY_BYTES)


def hash_password(
    password: str, *, log2_n: int = DEFAULT_LOG2_N, r: int = DEFAULT_R, p: int = DEFAULT_P
) -> str:
    """Return a salted scrypt hash of ``password`` in the stored format."""
    salt = secrets.token_bytes(_SALT_BYTES)
    key = _derive(password, salt, log2_n, r, p)
    return f"{SCHEME}${log2_n}${r}${p}${_b64encode(salt)}${_b64encode(key)}"


def _parse(encoded: str) -> tuple[int, int, int, bytes, bytes] | None:
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        return None
    try:
        log2_n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt, key = _b64decode(parts[4]), _b64decode(parts[5])
    except (ValueError, binascii.Error):
        return None
    if not (1 <= log2_n <= _MAX_LOG2_N and 1 <= r <= _MAX_R and 1 <= p <= _MAX_P):
        return None
    if len(salt) < 8 or len(key) != _KEY_BYTES:
        return None
    return log2_n, r, p, salt, key


def is_password_hash(value: object) -> bool:
    """True when ``value`` is a well-formed hash produced by :func:`hash_password`."""
    return isinstance(value, str) and _parse(value) is not None


def verify_password(candidate: str, encoded: str) -> bool:
    """Check ``candidate`` against a stored hash; the final compare is constant-time."""
    parsed = _parse(encoded)
    if parsed is None:
        return False
    log2_n, r, p, salt, expected = parsed
    actual = _derive(candidate, salt, log2_n, r, p)
    return secrets.compare_digest(actual, expected)
