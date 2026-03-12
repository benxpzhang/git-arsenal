"""
Conversation service — CRUD operations for chat sessions and messages.
"""
from datetime import datetime, timezone
from sqlalchemy import select, func, update
from db import get_session
from models.orm import Conversation, Message


async def create_conversation(user_id: str, title: str | None = None) -> dict:
    """Create a new conversation for a user."""
    async with get_session() as session:
        conv = Conversation(user_id=user_id, title=title)
        session.add(conv)
        await session.flush()
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at.isoformat(),
            "updated_at": conv.updated_at.isoformat(),
            "message_count": 0,
        }


async def list_conversations(user_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """List conversations for a user, most recent first."""
    async with get_session() as session:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await session.execute(stmt)
        convs = result.scalars().all()

        out = []
        for conv in convs:
            count_stmt = select(func.count()).select_from(Message).where(
                Message.conversation_id == conv.id
            )
            count_result = await session.execute(count_stmt)
            msg_count = count_result.scalar() or 0

            out.append({
                "id": conv.id,
                "title": conv.title,
                "created_at": conv.created_at.isoformat(),
                "updated_at": conv.updated_at.isoformat(),
                "message_count": msg_count,
            })
        return out


async def get_conversation(user_id: str, conversation_id: str) -> dict | None:
    """Get a conversation with all its messages."""
    async with get_session() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None

        msg_result = await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
        )
        messages = msg_result.scalars().all()

        return {
            "id": conv.id,
            "title": conv.title,
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "tool_name": m.tool_name,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }


async def add_message(
    user_id: str,
    conversation_id: str,
    role: str,
    content: str,
    tool_name: str | None = None,
    tool_input: str | None = None,
    tool_output: str | None = None,
) -> dict | None:
    """Add a message to a conversation. Returns the message or None if unauthorized."""
    async with get_session() as session:
        # Verify ownership
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return None

        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
        )
        session.add(msg)

        # Update conversation timestamp
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(timezone.utc))
        )
        await session.flush()

        return {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "tool_name": msg.tool_name,
            "created_at": msg.created_at.isoformat(),
        }


async def delete_conversation(user_id: str, conversation_id: str) -> bool:
    """Delete a conversation. Returns True if deleted."""
    async with get_session() as session:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )
        conv = result.scalar_one_or_none()
        if not conv:
            return False
        await session.delete(conv)
        return True
