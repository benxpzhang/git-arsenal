"""
Qdrant vector search service.

Handles:
  - Single-vector search (tree only, v1.0)
  - Dual-vector search with RRF fusion (tree + wiki, future)
  - Filtered search (language, stars)
"""
from qdrant_client import QdrantClient, models
from config import QDRANT_URL, QDRANT_COLLECTION

_client: QdrantClient | None = None


def init_qdrant():
    """Initialize Qdrant client and verify collection."""
    global _client
    _client = QdrantClient(url=QDRANT_URL, timeout=30)
    info = _client.get_collection(QDRANT_COLLECTION)
    print(f"  Qdrant: {info.points_count:,} points in '{QDRANT_COLLECTION}'")


def get_client() -> QdrantClient:
    if _client is None:
        raise RuntimeError("Qdrant not initialized. Call init_qdrant() first.")
    return _client


async def search_repos(
    tree_vector: list[float],
    wiki_vector: list[float] | None = None,
    top_k: int = 15,
    language: str | None = None,
    min_stars: int | None = None,
) -> list[dict]:
    """
    Search repos by vector similarity.

    Args:
        tree_vector: 1024-dim embedding of hypothetical repo tree
        wiki_vector: 1024-dim embedding of wiki summary (optional, for dual-vector)
        top_k: number of results
        language: filter by programming language
        min_stars: filter by minimum star count

    Returns:
        List of dicts with repo info + score
    """
    client = get_client()

    # Build filters
    conditions = []
    if language:
        conditions.append(
            models.FieldCondition(
                key="language",
                match=models.MatchValue(value=language),
            )
        )
    if min_stars is not None and min_stars > 0:
        conditions.append(
            models.FieldCondition(
                key="stars",
                range=models.Range(gte=min_stars),
            )
        )

    query_filter = models.Filter(must=conditions) if conditions else None

    # qdrant-client >= 1.12 removed .search(); use .query_points() instead.
    # Collection "repos" uses a named vector "tree" (1024-dim cosine).
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=tree_vector,
        using="tree",
        limit=top_k,
        query_filter=query_filter,
        with_payload=True,
        with_vectors=False,
    )

    return [
        {
            "id": hit.id,
            "score": round(hit.score, 4),
            "full_name": hit.payload.get("full_name", ""),
            "stars": hit.payload.get("stars", 0),
            "language": hit.payload.get("language", ""),
            "description": hit.payload.get("description", ""),
            "html_url": hit.payload.get("html_url", ""),
            "tree_text": hit.payload.get("tree_text", ""),
        }
        for hit in response.points
    ]


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
    return {
        "id": hit.id,
        "full_name": hit.payload.get("full_name", ""),
        "stars": hit.payload.get("stars", 0),
        "language": hit.payload.get("language", ""),
        "description": hit.payload.get("description", ""),
        "html_url": hit.payload.get("html_url", ""),
        "tree_text": hit.payload.get("tree_text", ""),
    }
