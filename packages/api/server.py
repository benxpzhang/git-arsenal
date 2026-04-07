"""
Git Arsenal - Backend API Server

Run: uvicorn server:app --host 0.0.0.0 --port 8003 --reload
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import API_HOST, API_PORT, CORS_ORIGINS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app):
    # Startup
    from db import init_db
    from services.search import init_qdrant
    from services.galaxy import load_galaxy_data

    await init_db()
    init_qdrant()
    load_galaxy_data()
    print("✅ Git Arsenal API ready")
    yield
    # Shutdown
    from db import close_db
    await close_db()


app = FastAPI(
    title="Git Arsenal API",
    description="AI Agent-driven open source project recommendation platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routes.search import router as search_router
from routes.galaxy import router as galaxy_router
from routes.auth import router as auth_router
from routes.conversation import router as conv_router

app.include_router(search_router)
app.include_router(galaxy_router)
app.include_router(auth_router)
app.include_router(conv_router)


@app.get("/api/health")
async def health():
    from services.search import get_client
    from services.galaxy import REPOS

    qdrant_ok = False
    qdrant_points = 0
    try:
        client = get_client()
        info = client.get_collection("repos")
        qdrant_ok = True
        qdrant_points = info.points_count
    except Exception:
        pass

    return {
        "status": "ok",
        "service": "git-arsenal-api",
        "version": "1.0.0",
        "repos_in_memory": len(REPOS),
        "qdrant_ok": qdrant_ok,
        "qdrant_points": qdrant_points,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host=API_HOST, port=API_PORT, reload=True)
