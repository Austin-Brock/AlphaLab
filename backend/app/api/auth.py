"""Owner-only access. Anyone may read; every change needs the admin key.

Reads (GET/HEAD) are public. Every other method requires
`Authorization: Bearer <ALPHALAB_ADMIN_KEY>`. The check is applied to the whole
app, so a new write endpoint is protected without opting in. With no key
configured, all writes are refused (fail closed).
"""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.config import get_settings

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_admin_key() -> str | None:
    key = get_settings().admin_key
    return key.get_secret_value() if key else None


def is_admin(request: Request, admin_key: Annotated[str | None, Depends(get_admin_key)]) -> bool:
    if not admin_key:
        return False
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return scheme.lower() == "bearer" and secrets.compare_digest(token.encode(), admin_key.encode())


IsAdmin = Annotated[bool, Depends(is_admin)]


def require_admin(admin: IsAdmin, admin_key: Annotated[str | None, Depends(get_admin_key)]) -> None:
    if admin:
        return
    if not admin_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Changes are disabled: ALPHALAB_ADMIN_KEY is not set on the server.",
        )
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "This action needs the owner's admin key.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin_for_writes(
    request: Request, admin: IsAdmin, admin_key: Annotated[str | None, Depends(get_admin_key)]
) -> None:
    if request.method not in READ_METHODS:
        require_admin(admin, admin_key)
