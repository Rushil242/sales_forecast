"""Encryption for stored OAuth tokens.

There is no login on this system -- one workspace, one operator -- so it would be
easy to argue that tokens could sit in the database as plain text. They should
not. A Shopify access token grants read access to a real shop's order history,
and the SQLite file gets copied to laptops, attached to bug reports and committed
by accident. Encrypting at rest costs nothing and removes that whole class of
mistake.

The key comes from ``RETAILIQ_SECRET_KEY``. If it is unset the process generates
an ephemeral one and says so plainly: tokens written this run become unreadable
after a restart, which is a nuisance rather than a silent failure, and the log
line tells the operator exactly how to fix it.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

LOG = logging.getLogger(__name__)

EPHEMERAL_WARNING = (
    "RETAILIQ_SECRET_KEY is not set, so connector tokens are encrypted with an "
    "ephemeral key and will not survive a restart. Set it to any long random "
    "string to persist connections."
)


@lru_cache(maxsize=1)
def _box() -> tuple[Fernet, bool]:
    """Return the cipher and whether its key is ephemeral."""
    secret = get_settings().secret_key
    if secret:
        # Fernet needs exactly 32 url-safe base64 bytes; a passphrase of any
        # length is hashed down to that rather than rejected.
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest)), False

    LOG.warning(EPHEMERAL_WARNING)
    return Fernet(Fernet.generate_key()), True


def key_is_ephemeral() -> bool:
    return _box()[1]


def encrypt(value: str | None) -> str | None:
    if value is None:
        return None
    return _box()[0].encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """Decrypt a stored token, or return ``None`` if the key no longer matches.

    A rotated or ephemeral key makes old tokens undecryptable. That is a
    reconnect prompt, not a crash, so the caller gets ``None`` and reports the
    account as needing reconnection.
    """
    if value is None:
        return None
    try:
        return _box()[0].decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        LOG.warning("Stored token could not be decrypted; the signing key has changed.")
        return None
