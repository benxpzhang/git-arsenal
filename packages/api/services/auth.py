"""
Authentication service — anonymous user registration + JWT tokens.

Flow:
  1. Frontend calls POST /api/auth/anonymous -> creates user + returns JWT
  2. Frontend stores JWT in localStorage
  3. All subsequent requests include Authorization: Bearer <token>
  4. Middleware extracts user_id from JWT
"""
import uuid
from datetime import datetime, timedelta, date, timezone
import jwt
from sqlalchemy import select, func
from config import JWT_SECRET, JWT_EXPIRE_DAYS, ANON_DAILY_QUOTA
from db import get_session
from models.orm import User, UsageLog


def create_token(user_id: str) -> str:
    """Create a JWT token for a user."""
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> str | None:
    """Decode a JWT token, return user_id or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


async def create_anonymous_user() -> dict:
    """Create a new anonymous user and return auth info."""
    user_id = str(uuid.uuid4())

    async with get_session() as session:
        user = User(
            id=user_id,
            auth_type="anonymous",
            daily_quota=ANON_DAILY_QUOTA,
        )
        session.add(user)

    token = create_token(user_id)
    return {
        "user_id": user_id,
        "token": token,
        "daily_quota": ANON_DAILY_QUOTA,
        "usage_today": 0,
    }


async def get_user_info(user_id: str) -> dict:
    """Get user info + today's usage."""
    async with get_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return None

        today = date.today()
        usage_result = await session.execute(
            select(UsageLog.search_count).where(
                UsageLog.user_id == user_id,
                UsageLog.date == today,
            )
        )
        usage_today = usage_result.scalar() or 0

        return {
            "user_id": user.id,
            "nickname": user.nickname,
            "auth_type": user.auth_type,
            "daily_quota": user.daily_quota,
            "usage_today": usage_today,
        }
