"""
Search API routes.

POST /api/search  - multi-recall search (requires auth + quota)
GET  /api/repo/...  - look up a single repo by name

Pipeline:
  Agent provides keywords + hypothetical_tree → backend embeds + recalls + RRF.
  If not provided, ONE LLM fallback call generates both.

  1. Resolve keywords + tree (Agent-provided or single LLM fallback)
  2. Parallel: embed tree + embed query
  3. Multi-recall + RRF merge
"""
import asyncio
import traceback
import time
from fastapi import APIRouter, Depends
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
    hypo_tree = req.hypothetical_tree or ""

    if not keywords or not hypo_tree:
        from services.query_parser import parse_query
        fb_kw, fb_tree = await asyncio.to_thread(parse_query, req.query)
        if not keywords:
            keywords = fb_kw
        if not hypo_tree:
            hypo_tree = fb_tree

    t1 = time.time()
    agent_provided = bool(req.keywords and req.hypothetical_tree)
    print(f"  Phase 1 (params): {t1 - t0:.2f}s | agent={agent_provided} | kw={len(keywords)}")
    print(f"  Keywords: {keywords}")

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
    t2 = time.time()
    print(f"  Phase 2 (embed): {t2 - t1:.2f}s")

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
    t3 = time.time()
    print(f"  Phase 3 (recall+RRF): {t3 - t2:.2f}s, {len(candidates)} results")
    print(f"  Total: {t3 - t0:.2f}s")

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
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Repo '{full_name}' not found")
    return result
