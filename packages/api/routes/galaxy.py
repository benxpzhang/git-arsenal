"""
Galaxy visualization API routes.

GET /api/galaxy/subgraph  - subgraph around a node
GET /api/galaxy/search    - name search for Galaxy nodes
GET /api/galaxy/detail    - single node details
GET /api/galaxy/cluster   - cluster-level subgraph
GET /api/galaxy/expand    - expand to parent cluster

Galaxy endpoints are public (no auth required) — they serve the visualization.
"""
import asyncio
from fastapi import APIRouter, Query
from services.galaxy import (
    get_subgraph, resolve_focus_idx, search_by_name,
    get_node_detail, get_neighbors, get_cluster_subgraph, expand_to_parent, REPOS,
)

router = APIRouter(prefix="/api/galaxy", tags=["galaxy"])


@router.get("/subgraph")
async def subgraph(
    node: str | None = None,
    id: int | None = None,
    random: bool = False,
    max_nodes: int = Query(300, ge=10, le=500),
):
    focus_idx = resolve_focus_idx(node, id, random)
    if focus_idx is None:
        return {"detail": "Could not resolve focus node. Provide ?node=, ?id=, or ?random=true"}
    return await asyncio.to_thread(get_subgraph, focus_idx, max_nodes)


@router.get("/search")
async def search(q: str, limit: int = Query(12, ge=1, le=50)):
    results = await asyncio.to_thread(search_by_name, q, limit)
    return {"query": q, "results": results}


@router.get("/neighbors")
async def neighbors(id: int, limit: int = Query(15, ge=1, le=30)):
    return await asyncio.to_thread(get_neighbors, id, limit)


@router.get("/detail")
async def detail(id: int):
    return await asyncio.to_thread(get_node_detail, id)


@router.get("/cluster")
async def cluster(
    cluster_id: int,
    focus_id: int | None = None,
    max_nodes: int = Query(300, ge=10, le=500),
):
    return await asyncio.to_thread(get_cluster_subgraph, cluster_id, focus_id, max_nodes)


@router.get("/expand")
async def expand(id: int, max_nodes: int = Query(300, ge=10, le=500)):
    return await asyncio.to_thread(expand_to_parent, id, max_nodes)
