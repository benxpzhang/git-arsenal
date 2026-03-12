"""
Search API routes.

POST /api/search  - semantic search with HyDE + Qdrant (requires auth + quota)
GET  /api/repo/...  - look up a single repo by name

Degradation chain:
  HyDE fail  -> use raw query for embedding (lower quality but works)
  Embed fail -> return empty results with error hint (no 500)
  Qdrant fail -> return empty results with error hint (no 500)
"""
import asyncio
import traceback
from fastapi import APIRouter, Depends
from models.schemas import SearchRequest, SearchResponse, RepoResult
from services.embedding import get_embedding, EmbeddingError
from services.hyde import generate_hypothetical_tree
from services.search import search_repos, get_repo_by_name
from services.usage import increment_usage
from middleware.auth import get_current_user
from middleware.rate_limit import check_search_quota

router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    user_id: str = Depends(get_current_user),
    _quota=Depends(check_search_quota),
):
    # Step 1: HyDE — generate hypothetical tree (or use provided one)
    if req.hypothetical_tree:
        hypo_tree = req.hypothetical_tree
    else:
        try:
            hypo_tree = await asyncio.to_thread(generate_hypothetical_tree, req.query)
        except Exception as e:
            print(f"  HyDE failed ({type(e).__name__}), using raw query")
            hypo_tree = req.query

    # Step 2: Embed
    try:
        tree_vector = await asyncio.to_thread(get_embedding, hypo_tree)
    except EmbeddingError as e:
        print(f"  Embedding failed: {e}")
        # Try with raw query as fallback
        try:
            tree_vector = await asyncio.to_thread(get_embedding, req.query)
        except EmbeddingError:
            return SearchResponse(query=req.query, hypothetical_tree=hypo_tree, results=[])

    # Step 3: Search Qdrant
    try:
        results = await search_repos(
            tree_vector=tree_vector,
            top_k=req.top_k,
            language=req.language,
            min_stars=req.min_stars,
        )
    except Exception as e:
        print(f"  Qdrant search failed: {e}")
        traceback.print_exc()
        return SearchResponse(query=req.query, hypothetical_tree=hypo_tree, results=[])

    # Step 4: Increment usage only on success
    await increment_usage(user_id)

    return SearchResponse(
        query=req.query,
        hypothetical_tree=hypo_tree,
        results=[RepoResult(**r) for r in results],
    )


@router.get("/repo/{owner}/{name}")
async def repo_detail(owner: str, name: str):
    full_name = f"{owner}/{name}"
    result = await get_repo_by_name(full_name)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Repo '{full_name}' not found")
    return result
