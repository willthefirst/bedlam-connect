"""Absolute-link construction for email bodies.

Email clients render outside the request scope, so every link in a
message must be absolute. `APP_BASE_URL` is validated (scheme required,
trailing slash stripped) in `src.framework.config`, so the join here is
a single `/`.
"""

from __future__ import annotations

from src.framework.config import settings


def absolute_url(path: str) -> str:
    """Join `APP_BASE_URL` with an app path (leading slash optional)."""
    return f"{settings.APP_BASE_URL}/{path.lstrip('/')}"
