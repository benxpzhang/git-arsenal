"""
Pydantic request/response schemas for the API.
"""
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., description="User's natural language query")
    hypothetical_tree: str | None = Field(None, description="Agent-generated hypothetical repo tree")
    wiki_summary: str | None = Field(None, description="Agent-generated project summary")
    top_k: int = Field(15, ge=1, le=50)
    language: str | None = Field(None, description="Filter by programming language")
    min_stars: int | None = Field(None, ge=0, description="Filter by minimum star count")


class RepoResult(BaseModel):
    id: int
    score: float
    full_name: str
    stars: int
    language: str
    description: str
    html_url: str
    tree_text: str


class SearchResponse(BaseModel):
    query: str
    hypothetical_tree: str
    results: list[RepoResult]


class AnonAuthResponse(BaseModel):
    user_id: str
    token: str
    daily_quota: int
    usage_today: int


class UserInfoResponse(BaseModel):
    user_id: str
    nickname: str | None
    auth_type: str
    daily_quota: int
    usage_today: int


class ConversationCreate(BaseModel):
    title: str | None = None


class ConversationOut(BaseModel):
    id: str
    title: str | None
    created_at: str
    updated_at: str
    message_count: int = 0


class MessageCreate(BaseModel):
    role: str = Field(..., description="Message role: user | assistant | tool | system")
    content: str = Field(..., description="Message text content")
    tool_name: str | None = None
    tool_input: str | None = None
    tool_output: str | None = None


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    tool_name: str | None = None
    created_at: str


class ConversationDetail(BaseModel):
    id: str
    title: str | None
    messages: list[MessageOut]
