"""
Qdrant vector search service.

Supports:
  - Multi-recall: name keyword + tree vector + wiki vector
  - RRF (Reciprocal Rank Fusion) merge
  - Single-vector fallback when wiki vectors are not available
"""
import asyncio
from qdrant_client import QdrantClient, models
from config import QDRANT_URL, QDRANT_COLLECTION

_client: QdrantClient | None = None
_has_wiki_vector: bool = False


def init_qdrant():
    """Initialize Qdrant client, verify collection, and detect vector config."""
    global _client, _has_wiki_vector
    _client = QdrantClient(url=QDRANT_URL, timeout=30)
    info = _client.get_collection(QDRANT_COLLECTION)
    print(f"  Qdrant: {info.points_count:,} points in '{QDRANT_COLLECTION}'")

    vec_cfg = info.config.params.vectors
    if isinstance(vec_cfg, dict):
        _has_wiki_vector = "wiki" in vec_cfg
        print(f"  Vectors: {list(vec_cfg.keys())}")
    else:
        _has_wiki_vector = False
        print("  Vectors: default (single)")


def get_client() -> QdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant not initialized. Call init_qdrant() first.")
    return _client


def _build_filter(language: str | None = None, min_stars: int | None = None) -> models.Filter | None:
    conditions = []
    if language:
        conditions.append(
            models.FieldCondition(key="language", match=models.MatchValue(value=language))
        )
    if min_stars is not None and min_stars > 0:
        conditions.append(
            models.FieldCondition(key="stars", range=models.Range(gte=min_stars))
        )
    return models.Filter(must=conditions) if conditions else None


def _hit_to_dict(hit) -> dict:
    return {
        "id": hit.id,
        "score": round(hit.score, 4) if hasattr(hit, 'score') else 0.0,
        "full_name": hit.payload.get("full_name", ""),
        "stars": hit.payload.get("stars", 0),
        "language": hit.payload.get("language", ""),
        "description": hit.payload.get("description", ""),
        "html_url": hit.payload.get("html_url", ""),
        "tree_text": hit.payload.get("tree_text", ""),
        "wiki_text": hit.payload.get("wiki_text", ""),
    }


def rrf_merge(result_lists: list[list[dict]], top_k: int = 30, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion: score = sum(1 / (k + rank_i)) across channels."""
    scores: dict[int, float] = {}
    data: dict[int, dict] = {}

    for results in result_lists:
        for rank, item in enumerate(results):
            rid = item["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            if rid not in data:
                data[rid] = item

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
    merged = []
    for rid in sorted_ids:
        item = data[rid].copy()
        item["rrf_score"] = round(scores[rid], 6)
        merged.append(item)
    return merged


async def recall_by_name(
    keywords: list[str],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    """Channel 1: Keyword recall via full_name text index, ordered by stars desc.

    Uses Qdrant's order_by to directly fetch the highest-star matches per keyword,
    avoiding the default point-ID ordering that misses popular high-ID repos.
    """
    if not keywords:
        return []

    client = get_client()
    per_kw_limit = max(limit // len(keywords) * 2, 20)
    seen_ids: set[int] = set()
    all_results: list[dict] = []

    for kw in keywords:
        try:
            conditions = [
                models.FieldCondition(key="full_name", match=models.MatchText(text=kw))
            ]
            if query_filter and query_filter.must:
                scroll_filter = models.Filter(must=query_filter.must + conditions)
            else:
                scroll_filter = models.Filter(must=conditions)

            points, _ = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=scroll_filter,
                limit=per_kw_limit,
                order_by=models.OrderBy(key="stars", direction=models.Direction.DESC),
                with_payload=True,
            )
            for p in points:
                if p.id not in seen_ids:
                    seen_ids.add(p.id)
                    all_results.append(_hit_to_dict(p))
        except Exception as e:
            print(f"  Name recall error for '{kw}': {e}")

    all_results.sort(key=lambda r: r["stars"], reverse=True)
    return all_results[:limit]


async def recall_by_tree(
    tree_vector: list[float],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    """Channel 2: Tree vector similarity search."""
    client = get_client()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=tree_vector,
        using="tree",
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
        with_vectors=False,
    )
    return [_hit_to_dict(hit) for hit in response.points]


async def recall_by_wiki(
    wiki_vector: list[float],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    """Channel 3: Wiki vector similarity search."""
    if not _has_wiki_vector:
        return []
    client = get_client()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=wiki_vector,
        using="wiki",
        limit=limit,
        query_filter=query_filter,
        with_payload=True,
        with_vectors=False,
    )
    return [_hit_to_dict(hit) for hit in response.points]


async def multi_recall(
    keywords: list[str],
    tree_vector: list[float],
    wiki_vector: list[float] | None = None,
    top_k_per_channel: int = 50,
    rrf_top_k: int = 30,
    language: str | None = None,
    min_stars: int | None = None,
) -> list[dict]:
    """
    Three-channel recall + RRF merge.

    Returns ~rrf_top_k candidates sorted by RRF score.
    """

    query_filter = _build_filter(language, min_stars)

    tasks = [
        recall_by_name(keywords, top_k_per_channel, query_filter),
        recall_by_tree(tree_vector, top_k_per_channel, query_filter),
    ]

    if wiki_vector and _has_wiki_vector:
        tasks.append(recall_by_wiki(wiki_vector, top_k_per_channel, query_filter))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results = []
    channel_names = ["name", "tree", "wiki"]
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            print(f"  Recall channel '{channel_names[i]}' failed: {r}")
            valid_results.append([])
        else:
            valid_results.append(r)
            print(f"  Recall '{channel_names[i]}': {len(r)} results")

    return rrf_merge(valid_results, top_k=rrf_top_k)


async def search_repos(
    tree_vector: list[float],
    wiki_vector: list[float] | None = None,
    keywords: list[str] | None = None,
    top_k: int = 15,
    language: str | None = None,
    min_stars: int | None = None,
) -> list[dict]:
    """
    Backward-compatible search interface.

    When wiki_vector is provided, uses multi-recall + RRF.
    Otherwise falls back to tree-only vector search.
    """
    if wiki_vector and _has_wiki_vector:
        candidates = await multi_recall(
            keywords=keywords or [],
            tree_vector=tree_vector,
            wiki_vector=wiki_vector,
            rrf_top_k=top_k,
            language=language,
            min_stars=min_stars,
        )
        return candidates

    # Fallback: tree-only search
    return await recall_by_tree(
        tree_vector=tree_vector,
        limit=top_k,
        query_filter=_build_filter(language, min_stars),
    )


async def get_repo_by_name(full_name: str) -> dict | None:
    """Look up a single repo by full_name (e.g. 'facebook/react')."""
    client = get_client()
    results = client.scroll(
        collection_name=QDRANT_COLLECTION,
        scroll_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="full_name",
                    match=models.MatchValue(value=full_name),
                )
            ]
        ),
        limit=1,
        with_payload=True,
    )
    points = results[0]
    if not points:
        return None
    hit = points[0]
    return _hit_to_dict(hit)
