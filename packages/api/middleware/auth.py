"""
Authentication middleware — extracts user_id from JWT Bearer token.

Usage in routes:
    from middleware.auth import get_current_user
    @router.post("/something")
    async def something(user_id: str = Depends(get_current_user)):
        ...
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from services.auth import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """
    Extract and validate JWT from Authorization header.
    Returns user_id or raises 401.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing authorization token")
    try:
        user_id = decode_token(credentials.credentials)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str | None:
    """
    Like get_current_user but returns None instead of 401.
    Useful for endpoints that work with or without auth (e.g. search).
    """
    if not credentials:
        return None
    try:
        return decode_token(credentials.credentials)
    except Exception:
        return None
