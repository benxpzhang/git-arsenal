"""
Rate limiting middleware — checks user's daily quota before allowing search.

Only checks quota; does NOT increment usage.
The route handler is responsible for calling increment_usage() after
a successful operation, so failed searches don't consume quota.

Usage in routes:
    from middleware.rate_limit import check_search_quota
    @router.post("/search")
    async def search(user_id: str = Depends(get_current_user), _=Depends(check_search_quota)):
        ...
        await increment_usage(user_id)   # only after success
"""
from fastapi import Depends, HTTPException
from middleware.auth import get_current_user
from services.usage import check_quota


async def check_search_quota(user_id: str = Depends(get_current_user)):
    """
    Dependency that checks search quota.
    Raises 429 if quota exceeded.
    Does NOT increment — caller must call increment_usage() on success.
    """
    allowed, usage_today, daily_quota = await check_quota(user_id)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Daily quota exceeded ({usage_today}/{daily_quota}). Try again tomorrow.",
        )
