"""
Search API routes.

POST /api/search  - multi-recall search (requires auth + quota)
GET  /api/repo/...  - look up a single repo by name

Pipeline:
  Agent provides keywords + repo_tree + repo_summary directly.
  1. Embed tree + embed query (parallel)
  2. Multi-recall (keyword + tree vec + wiki vec) + RRF merge
"""
import asyncio
import logging
import time
from fastapi import APIRouter, Depends, HTTPException
from models.schemas import SearchRequest, SearchResponse, RepoResult
from services.embedding import get_embedding, EmbeddingError
from services.search import multi_recall, get_repo_by_name, search_repo_by_name
from services.usage import increment_usage
from middleware.auth import get_current_user
from middleware.rate_limit import check_search_quota

log = logging.getLogger("arsenal.search")
router = APIRouter(prefix="/api", tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    user_id: str = Depends(get_current_user),
    _quota=Depends(check_search_quota),
):
    t0 = time.time()

    keywords = req.keywords or []
    hypo_tree = req.repo_tree or req.query
    hypo_wiki = req.repo_summary or req.query

    log.info(
        "=== SEARCH query=%r  top_k=%d  keywords=%s  lang=%s  min_stars=%s",
        req.query[:80], req.top_k, keywords, req.language, req.min_stars,
    )
    if req.repo_tree:
        log.info("  hypo_tree (first 120 chars): %s", req.repo_tree[:120])
    if req.repo_summary:
        log.info("  hypo_wiki (first 120 chars): %s", req.repo_summary[:120])

    async def embed_tree():
        try:
            return await asyncio.to_thread(get_embedding, hypo_tree)
        except EmbeddingError as e:
            log.warning("  embed_tree failed: %s — fallback to query", e)
            try:
                return await asyncio.to_thread(get_embedding, req.query)
            except EmbeddingError:
                return None

    async def embed_wiki():
        try:
            return await asyncio.to_thread(get_embedding, hypo_wiki)
        except EmbeddingError as e:
            log.warning("  embed_wiki failed: %s", e)
            return None

    tree_vector, wiki_vector = await asyncio.gather(embed_tree(), embed_wiki())
    t1 = time.time()
    log.info("  embed: %.2fs  tree_vec=%s  wiki_vec=%s",
             t1 - t0, "OK" if tree_vector else "NONE", "OK" if wiki_vector else "NONE")

    if tree_vector is None:
        log.warning("  ABORT: no tree vector")
        return SearchResponse(query=req.query, repo_tree=hypo_tree, results=[])

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
        log.error("  RECALL FAILED: %s", e, exc_info=True)
        return SearchResponse(query=req.query, repo_tree=hypo_tree, results=[])

    t2 = time.time()
    log.info("  recall+rrf: %.2fs  %d results", t2 - t1, len(candidates))
    log.info("  TOTAL: %.2fs", t2 - t0)

    await increment_usage(user_id)

    return SearchResponse(
        query=req.query,
        repo_tree=hypo_tree,
        results=[RepoResult(**r) for r in candidates],
    )


@router.get("/repo/{owner}/{name}")
async def repo_detail(owner: str, name: str):
    full_name = f"{owner}/{name}"
    log.info("=== REPO_DETAIL exact=%s", full_name)
    result = await get_repo_by_name(full_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Repo '{full_name}' not found")
    return result


@router.get("/repo-search/{name}")
async def repo_search_by_name(name: str):
    """Find the most popular repo matching a partial name (no owner required)."""
    log.info("=== REPO_SEARCH fuzzy=%s", name)
    result = await search_repo_by_name(name)
    if not result:
        raise HTTPException(status_code=404, detail=f"No repo matching '{name}' found")
    return result
