"""
Conversation API routes.

POST   /api/conversations              - create conversation
GET    /api/conversations              - list conversations
GET    /api/conversations/{id}         - get conversation with messages
POST   /api/conversations/{id}/messages - add message
DELETE /api/conversations/{id}         - delete conversation
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from middleware.auth import get_current_user
from models.schemas import ConversationCreate, ConversationOut, ConversationDetail, MessageCreate, MessageOut
from services.conversation import (
    create_conversation, list_conversations, get_conversation, add_message, delete_conversation,
)

router = APIRouter(prefix="/api/conversations", tags=["conversation"])


@router.post("", response_model=ConversationOut)
async def create(req: ConversationCreate, user_id: str = Depends(get_current_user)):
    return await create_conversation(user_id, req.title)


@router.get("", response_model=list[ConversationOut])
async def list_all(
    user_id: str = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    return await list_conversations(user_id, limit, offset)


@router.get("/{conv_id}", response_model=ConversationDetail)
async def get_detail(conv_id: str, user_id: str = Depends(get_current_user)):
    result = await get_conversation(user_id, conv_id)
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return result


@router.post("/{conv_id}/messages", response_model=MessageOut)
async def post_message(conv_id: str, req: MessageCreate, user_id: str = Depends(get_current_user)):
    result = await add_message(
        user_id, conv_id,
        role=req.role, content=req.content,
        tool_name=req.tool_name, tool_input=req.tool_input, tool_output=req.tool_output,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Conversation not found or unauthorized")
    return result


@router.delete("/{conv_id}")
async def delete(conv_id: str, user_id: str = Depends(get_current_user)):
    success = await delete_conversation(user_id, conv_id)
    if not success:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"detail": "Deleted"}
