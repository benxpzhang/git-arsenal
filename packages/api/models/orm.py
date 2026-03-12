# Source Generated with Decompyle++
# File: orm.cpython-311.pyc (Python 3.11)

'''
SQLAlchemy ORM models.

Tables:
  users        — anonymous users (UUID identity)
  conversations — chat sessions
  messages     — individual messages in a conversation
  usage_logs   — daily API usage tracking for quota
'''
import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Integer, Text, DateTime, Date, ForeignKey, Index
from sqlalchemy.orm import declarative_base, relationship
Base = declarative_base()

def _uuid():
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = 'users'
    id = Column(String(36), primary_key = True, default = _uuid)
    nickname = Column(String(64), nullable = True)
    auth_type = Column(String(16), default = 'anonymous')
    daily_quota = Column(Integer, default = 20)
    created_at = Column(DateTime, default = datetime.utcnow)
    conversations = relationship('Conversation', back_populates = 'user', cascade = 'all, delete-orphan')
    usage_logs = relationship('UsageLog', back_populates = 'user', cascade = 'all, delete-orphan')


class Conversation(Base):
    __tablename__ = 'conversations'
    id = Column(String(36), primary_key = True, default = _uuid)
    user_id = Column(String(36), ForeignKey('users.id', ondelete = 'CASCADE'), nullable = False)
    title = Column(String(256), nullable = True)
    created_at = Column(DateTime, default = datetime.utcnow)
    updated_at = Column(DateTime, default = datetime.utcnow, onupdate = datetime.utcnow)
    user = relationship('User', back_populates = 'conversations')
    messages = relationship('Message', back_populates = 'conversation', cascade = 'all, delete-orphan', order_by = 'Message.created_at')
    __table_args__ = (Index('ix_conv_user_updated', 'user_id', 'updated_at'),)


class Message(Base):
    __tablename__ = 'messages'
    id = Column(String(36), primary_key = True, default = _uuid)
    conversation_id = Column(String(36), ForeignKey('conversations.id', ondelete = 'CASCADE'), nullable = False)
    role = Column(String(16), nullable = False)
    content = Column(Text, nullable = False)
    tool_name = Column(String(64), nullable = True)
    tool_input = Column(Text, nullable = True)
    tool_output = Column(Text, nullable = True)
    created_at = Column(DateTime, default = datetime.utcnow)
    conversation = relationship('Conversation', back_populates = 'messages')
    __table_args__ = (Index('ix_msg_conv_created', 'conversation_id', 'created_at'),)


class UsageLog(Base):
    __tablename__ = 'usage_logs'
    id = Column(Integer, primary_key = True, autoincrement = True)
    user_id = Column(String(36), ForeignKey('users.id', ondelete = 'CASCADE'), nullable = False)
    date = Column(Date, default = date.today, nullable = False)
    search_count = Column(Integer, default = 0)
    user = relationship('User', back_populates = 'usage_logs')
    __table_args__ = (Index('ix_usage_user_date', 'user_id', 'date', unique = True),)

