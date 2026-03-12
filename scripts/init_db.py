"""
Initialize the PostgreSQL database schema.

Usage:
    cd packages/api && python -m scripts.init_db
  OR
    python scripts/init_db.py
"""
import sys
import asyncio
from pathlib import Path

# Add API package to path
api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from config import DATABASE_URL
from models.orm import Base


async def init():
    from sqlalchemy.ext.asyncio import create_async_engine
    engine = create_async_engine(DATABASE_URL, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    print("Database tables created successfully!")


if __name__ == "__main__":
    asyncio.run(init())
