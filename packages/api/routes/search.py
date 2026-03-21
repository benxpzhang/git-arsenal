"""
Search API routes.

POST /api/search  - multi-recall search (requires auth + quota)
GET  /api/repo/...  - look up a single repo by name

Pipeline:
  Agent provides keywords + hypothetical_tree directly.
  1. Embed tree + embed query (parallel)
  2. Multi-recall (keyword + tree vec + wiki vec) + RRF merge
"""
import asyncio
import traceback
import time
from fastapi import APIRouter, Depends, HTTPException
from models.schemas import SearchRequest, SearchResponse, RepoResult
from services.embedding import get_embedding, EmbeddingError
from services.search import multi_recall, get_repo_by_name
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
    t0 = time.time()

    keywords = req.keywords or []
    hypo_tree = req.hypothetical_tree or req.query

    if not keywords:
        print(f"  Warning: no keywords provided for query: {req.query[:60]}")

    print(f"  Keywords({len(keywords)}): {keywords}")

    # Parallel: embed tree + embed query
    async def embed_tree():
        try:
            return await asyncio.to_thread(get_embedding, hypo_tree)
        except EmbeddingError as e:
            print(f"  Tree embed failed: {e}")
            try:
                return await asyncio.to_thread(get_embedding, req.query)
            except EmbeddingError:
                return None

    async def embed_query():
        try:
            return await asyncio.to_thread(get_embedding, req.query)
        except EmbeddingError as e:
            print(f"  Wiki embed failed: {e}")
            return None

    tree_vector, wiki_vector = await asyncio.gather(embed_tree(), embed_query())
    t1 = time.time()
    print(f"  Embed: {t1 - t0:.2f}s")

    if tree_vector is None:
        return SearchResponse(query=req.query, hypothetical_tree=hypo_tree, results=[])

    # Multi-recall + RRF
    try:
        candidates = await multi_recall(
            keywords=keywords,
            tree_vector=tree_vector,
            wiki_vector=wiki_vector,
            top_k_per_channel=50,
            rrf_top_k=req.top_k,
            language=req.language,
            min_stars=req.min_stars,
        )
    except Exception as e:
        print(f"  Recall failed: {e}")
        traceback.print_exc()
        return SearchResponse(query=req.query, hypothetical_tree=hypo_tree, results=[])
    t2 = time.time()
    print(f"  Recall+RRF: {t2 - t1:.2f}s, {len(candidates)} results")
    print(f"  Total: {t2 - t0:.2f}s")

    await increment_usage(user_id)

    return SearchResponse(
        query=req.query,
        hypothetical_tree=hypo_tree,
        results=[RepoResult(**r) for r in candidates],
    )


@router.get("/repo/{owner}/{name}")
async def repo_detail(owner: str, name: str):
    full_name = f"{owner}/{name}"
    result = await get_repo_by_name(full_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Repo '{full_name}' not found")
    return result
