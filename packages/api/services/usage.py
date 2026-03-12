"""
Usage / quota service — tracks daily API usage per user.

Uses PostgreSQL atomic UPSERT (INSERT ... ON CONFLICT ... DO UPDATE)
to safely handle concurrent requests without race conditions.
"""
from datetime import date
from sqlalchemy import select, text
from db import get_session
from models.orm import User, UsageLog


async def check_quota(user_id: str) -> tuple[bool, int, int]:
    """
    Check if user has remaining quota today.

    Returns: (allowed, usage_today, daily_quota)
    """
    async with get_session() as session:
        # Get user's daily quota
        result = await session.execute(select(User.daily_quota).where(User.id == user_id))
        daily_quota = result.scalar()
        if daily_quota is None:
            return (False, 0, 0)

        # Get today's usage
        today = date.today()
        usage_result = await session.execute(
            select(UsageLog.search_count).where(
                UsageLog.user_id == user_id,
                UsageLog.date == today,
            )
        )
        usage_today = usage_result.scalar() or 0

        allowed = usage_today < daily_quota
        return (allowed, usage_today, daily_quota)


async def increment_usage(user_id: str) -> int:
    """
    Atomically increment today's search count for user.

    Uses INSERT ... ON CONFLICT ... DO UPDATE (PostgreSQL UPSERT)
    to avoid race conditions under concurrent requests.

    Returns: new search_count for today.
    """
    today = date.today()
    async with get_session() as session:
        result = await session.execute(
            text("""
                INSERT INTO usage_logs (user_id, date, search_count)
                VALUES (:user_id, :today, 1)
                ON CONFLICT (user_id, date)
                DO UPDATE SET search_count = usage_logs.search_count + 1
                RETURNING search_count
            """),
            {"user_id": user_id, "today": today},
        )
        return result.scalar()
