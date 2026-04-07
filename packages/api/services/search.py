"""
Qdrant vector search service.

Supports:
  - Multi-recall: name keyword + tree vector + wiki vector
  - RRF (Reciprocal Rank Fusion) merge with star-boost and per-channel pinning
  - Single-vector fallback when wiki vectors are not available
"""
import asyncio
import logging
import math
import time
from qdrant_client import QdrantClient, models
from config import QDRANT_URL, QDRANT_COLLECTION

log = logging.getLogger("arsenal.search")

_client: QdrantClient | None = None
_has_wiki_vector: bool = False

CHANNEL_TOP_N = 5
MIN_PIN_SCORE = 0.40

LIGHT_PAYLOAD = ["full_name", "stars", "language", "description", "html_url"]
FULL_PAYLOAD = LIGHT_PAYLOAD + ["tree_text", "wiki_text"]


def init_qdrant():
    global _client, _has_wiki_vector
    _client = QdrantClient(url=QDRANT_URL, timeout=30)
    info = _client.get_collection(QDRANT_COLLECTION)
    log.info("Qdrant: %s points in '%s'", f"{info.points_count:,}", QDRANT_COLLECTION)

    vec_cfg = info.config.params.vectors
    if isinstance(vec_cfg, dict):
        _has_wiki_vector = "wiki" in vec_cfg
        log.info("Vectors: %s", list(vec_cfg.keys()))
    else:
        _has_wiki_vector = False
        log.info("Vectors: default (single)")


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


def _hit_to_dict(hit, full: bool = False) -> dict:
    """Convert a Qdrant hit/scroll point to a plain dict.

    full=False (default) for recall phase: skips tree_text/wiki_text.
    full=True for final results: includes everything.
    """
    d = {
        "id": hit.id,
        "score": round(hit.score, 4) if hasattr(hit, "score") else 0.0,
        "full_name": hit.payload.get("full_name") or "",
        "stars": hit.payload.get("stars") or 0,
        "language": hit.payload.get("language") or "",
        "description": hit.payload.get("description") or "",
        "html_url": hit.payload.get("html_url") or "",
    }
    if full:
        d["tree_text"] = hit.payload.get("tree_text") or ""
        d["wiki_text"] = hit.payload.get("wiki_text") or ""
    return d


def _format_top(items: list[dict], n: int = 5, with_score: bool = False) -> str:
    parts = []
    for h in items[:n]:
        s = f"{h['full_name']}(⭐{h['stars']}"
        if with_score:
            s += f",s={h['score']:.3f}"
        s += ")"
        parts.append(s)
    return ", ".join(parts) or "(empty)"


# ── RRF Merge ──────────────────────────────────────────

def rrf_merge(
    result_lists: list[list[dict]],
    top_k: int = 30,
    k: int = 60,
    channel_names: list[str] | None = None,
) -> list[dict]:
    """
    Reciprocal Rank Fusion with log-star boost + per-channel star-pinning.

    1. base  = sum(1/(k+rank_i)) across channels
    2. boost = log2(1 + stars) / 300
    3. Pin top-CHANNEL_TOP_N by stars from each channel (vector channels
       require score >= MIN_PIN_SCORE to avoid irrelevant high-star noise).
    """
    ch_names = channel_names or [f"ch{i}" for i in range(len(result_lists))]

    scores: dict[int, float] = {}
    channel_ranks: dict[int, dict[str, int]] = {}
    data: dict[int, dict] = {}

    for ch_idx, results in enumerate(result_lists):
        ch = ch_names[ch_idx]
        for rank, item in enumerate(results):
            rid = item["id"]
            scores[rid] = scores.get(rid, 0.0) + 1.0 / (k + rank)
            channel_ranks.setdefault(rid, {})[ch] = rank
            if rid not in data:
                data[rid] = item

    for rid in scores:
        stars = data[rid].get("stars", 0)
        if stars > 0:
            scores[rid] += math.log2(1 + stars) / 300

    # Per-channel top N by stars → pinned set
    pinned_ids: set[int] = set()
    for ch_idx, results in enumerate(result_lists):
        ch = ch_names[ch_idx]
        is_vector_ch = ch in ("tree", "wiki")

        candidates = results
        if is_vector_ch:
            candidates = [r for r in results if r.get("score", 0) >= MIN_PIN_SCORE]

        by_stars = sorted(candidates, key=lambda x: x["stars"], reverse=True)[:CHANNEL_TOP_N]
        for item in by_stars:
            pinned_ids.add(item["id"])
        log.info("  ch[%s] top%d by stars: %s", ch, CHANNEL_TOP_N, _format_top(by_stars))

    # Main ranking
    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
    merged_set = set(sorted_ids)
    merged = []

    for i, rid in enumerate(sorted_ids):
        item = data[rid].copy()
        item["rrf_score"] = round(scores[rid], 6)
        merged.append(item)
        if i < 5:
            ch_str = ", ".join(
                f"{c}#{r}" for c, r in sorted(channel_ranks.get(rid, {}).items())
            )
            log.info(
                "  RRF #%d: %-40s ⭐%-7d rrf=%.4f  ch=[%s]",
                i + 1, data[rid].get("full_name", "?"),
                data[rid].get("stars", 0), scores[rid], ch_str,
            )

    # Append pinned items that RRF missed
    pinned_extra = [
        data[rid] for rid in pinned_ids
        if rid not in merged_set
    ]
    if pinned_extra:
        pinned_extra.sort(key=lambda x: x["stars"], reverse=True)
        for item in pinned_extra:
            copy = item.copy()
            copy["rrf_score"] = round(scores.get(item["id"], 0.0), 6)
            merged.append(copy)
        log.info("  PINNED %d extra: %s", len(pinned_extra), _format_top(pinned_extra))

    return merged


# ── Recall Channels ────────────────────────────────────

def _recall_single_keyword_sync(
    kw: str,
    per_kw_limit: int,
    query_filter: models.Filter | None,
) -> list[dict]:
    client = get_client()
    t0 = time.time()
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
            with_payload=LIGHT_PAYLOAD,
        )
        hits = [_hit_to_dict(p) for p in points]
        log.info("  keyword[%s]: %d hits in %.2fs | top5: %s",
                 kw, len(hits), time.time() - t0, _format_top(hits))
        return hits
    except Exception as e:
        log.error("  keyword[%s] error in %.2fs: %s", kw, time.time() - t0, e)
        return []


async def recall_by_name(
    keywords: list[str],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    if not keywords:
        return []
    per_kw_limit = max(limit // len(keywords) * 2, 20)
    tasks = [
        asyncio.to_thread(_recall_single_keyword_sync, kw, per_kw_limit, query_filter)
        for kw in keywords
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set[int] = set()
    combined: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            continue
        for item in r:
            if item["id"] not in seen:
                seen.add(item["id"])
                combined.append(item)

    combined.sort(key=lambda x: x["stars"], reverse=True)
    return combined[:limit]


def _query_points_sync(vector: list[float], using: str, limit: int, query_filter) -> list[dict]:
    client = get_client()
    t0 = time.time()
    response = client.query_points(
        collection_name=QDRANT_COLLECTION,
        query=vector,
        using=using,
        limit=limit,
        query_filter=query_filter,
        with_payload=LIGHT_PAYLOAD,
        with_vectors=False,
    )
    hits = [_hit_to_dict(hit) for hit in response.points]
    log.info("  vec[%s]: %d hits in %.2fs | top5: %s",
             using, len(hits), time.time() - t0, _format_top(hits, with_score=True))
    return hits


async def recall_by_tree(
    tree_vector: list[float],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    return await asyncio.to_thread(_query_points_sync, tree_vector, "tree", limit, query_filter)


async def recall_by_wiki(
    wiki_vector: list[float],
    limit: int = 50,
    query_filter: models.Filter | None = None,
) -> list[dict]:
    if not _has_wiki_vector:
        return []
    return await asyncio.to_thread(_query_points_sync, wiki_vector, "wiki", limit, query_filter)


# ── Multi-recall Orchestration ─────────────────────────

def _backfill_full_payload(items: list[dict]) -> list[dict]:
    """Fetch tree_text + wiki_text for final results only."""
    if not items:
        return items
    client = get_client()
    ids = [item["id"] for item in items]
    try:
        points = client.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=ids,
            with_payload=["tree_text", "wiki_text"],
            with_vectors=False,
        )
        payload_map = {p.id: p.payload for p in points}
    except Exception as e:
        log.warning("  backfill payload failed: %s", e)
        payload_map = {}

    for item in items:
        extra = payload_map.get(item["id"], {})
        item["tree_text"] = extra.get("tree_text") or ""
        item["wiki_text"] = extra.get("wiki_text") or ""
    return items


async def multi_recall(
    keywords: list[str],
    tree_vector: list[float],
    wiki_vector: list[float] | None = None,
    top_k_per_channel: int = 50,
    rrf_top_k: int = 30,
    language: str | None = None,
    min_stars: int | None = None,
) -> list[dict]:
    """Three-channel recall + RRF merge, then backfill full payload."""

    query_filter = _build_filter(language, min_stars)

    tasks = [
        recall_by_name(keywords, top_k_per_channel, query_filter),
        recall_by_tree(tree_vector, top_k_per_channel, query_filter),
    ]

    if wiki_vector and _has_wiki_vector:
        tasks.append(recall_by_wiki(wiki_vector, top_k_per_channel, query_filter))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    valid_results = []
    ch_names = ["name", "tree", "wiki"]
    for i, r in enumerate(results):
        ch = ch_names[i] if i < len(ch_names) else f"ch{i}"
        if isinstance(r, Exception):
            log.warning("  channel[%s] FAILED: %s", ch, r)
            valid_results.append([])
        else:
            valid_results.append(r)

    merged = rrf_merge(valid_results, top_k=rrf_top_k, channel_names=ch_names)

    return await asyncio.to_thread(_backfill_full_payload, merged)


# ── Single-repo Lookups ────────────────────────────────

def _get_repo_by_name_sync(full_name: str) -> dict | None:
    client = get_client()
    t0 = time.time()
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
        log.info("  repo_exact[%s]: NOT FOUND (%.2fs)", full_name, time.time() - t0)
        return None
    hit = _hit_to_dict(points[0], full=True)
    log.info("  repo_exact[%s]: found ⭐%d (%.2fs)", full_name, hit["stars"], time.time() - t0)
    return hit


async def get_repo_by_name(full_name: str) -> dict | None:
    return await asyncio.to_thread(_get_repo_by_name_sync, full_name)


def _search_repo_by_name_sync(name: str) -> dict | None:
    """Fuzzy match: find the highest-star repo whose full_name contains `name`."""
    client = get_client()
    t0 = time.time()
    try:
        points, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="full_name",
                        match=models.MatchText(text=name),
                    )
                ]
            ),
            limit=5,
            order_by=models.OrderBy(key="stars", direction=models.Direction.DESC),
            with_payload=True,
        )
        if not points:
            log.info("  repo_fuzzy[%s]: NOT FOUND (%.2fs)", name, time.time() - t0)
            return None
        hits = [_hit_to_dict(p, full=True) for p in points]
        log.info("  repo_fuzzy[%s]: picked %s ⭐%d | candidates: %s (%.2fs)",
                 name, hits[0]["full_name"], hits[0]["stars"],
                 _format_top(hits, n=3), time.time() - t0)
        return hits[0]
    except Exception as e:
        log.error("  repo_fuzzy[%s] error: %s (%.2fs)", name, e, time.time() - t0)
        return None


async def search_repo_by_name(name: str) -> dict | None:
    return await asyncio.to_thread(_search_repo_by_name_sync, name)
