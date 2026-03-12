"""
PostgreSQL async connection pool via SQLAlchemy 2.0.

Usage in services:
    from db import get_session
    async with get_session() as session:
        result = await session.execute(select(User).where(...))
"""
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from contextlib import asynccontextmanager
from config import DATABASE_URL

engine = None
async_session_factory = None


async def init_db():
    """Create the async engine and session factory."""
    global engine, async_session_factory
    engine = create_async_engine(DATABASE_URL, echo=False, pool_size=5, max_overflow=10)
    async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    print(f"  🐘 PostgreSQL connected: {DATABASE_URL.split('@')[-1]}")


async def close_db():
    """Dispose the engine."""
    global engine
    if engine:
        await engine.dispose()
        print("  🐘 PostgreSQL disconnected")


@asynccontextmanager
async def get_session():
    """Yield an async session for database operations."""
    if async_session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
