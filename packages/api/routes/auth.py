"""
Auth API routes.

POST /api/auth/anonymous  - create anonymous user + get JWT
GET  /api/auth/me         - get current user info + usage
"""
from fastapi import APIRouter, Depends
from middleware.auth import get_current_user
from services.auth import create_anonymous_user, get_user_info
from models.schemas import AnonAuthResponse, UserInfoResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/anonymous", response_model=AnonAuthResponse)
async def anonymous_login():
    return await create_anonymous_user()


@router.get("/me", response_model=UserInfoResponse)
async def me(user_id: str = Depends(get_current_user)):
    info = await get_user_info(user_id)
    if not info:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")
    return info
