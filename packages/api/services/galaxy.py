"""
Galaxy visualization service — loads and serves 3D graph data.

Data layout (unified/):
  - meta_index.jsonl          -> lightweight metadata with shard pointers
  - starmap/positions_3d.npy  -> UMAP 3D coordinates (N, 3)
  - starmap/galaxy_edges.npz  -> pre-computed kNN edges
  - starmap/cluster_tree.json -> hierarchical cluster tree
  - starmap/repo_leaf_labels.npy -> per-repo leaf cluster assignment
  - {YYYY}/{YYYY-MM}.jsonl    -> full shard data (on-demand detail)
"""
import json
import math
import random as rnd
from pathlib import Path
import numpy as np
from config import DATA_DIR

# ── Module-level data (loaded once at startup) ──
REPOS: list[dict] = []
POSITIONS: np.ndarray | None = None
LEAF_LABELS: np.ndarray | None = None
EDGE_SRC: np.ndarray | None = None
EDGE_DST: np.ndarray | None = None
EDGE_SIM: np.ndarray | None = None
CLUSTER_TREE: dict | None = None
CLUSTER_NODES: list[dict] = []
CLUSTER_NODE_MAP: dict[int, dict] = {}
REPO_NAME_TO_IDX: dict[str, int] = {}
REPO_SHARD: list[str] = []       # shard relative path per repo
REPO_SHARD_LINE: list[int] = []  # line number in shard per repo
HUB_INDICES: list[int] = []

# Language -> color mapping
LANG_COLORS = {
    "Python": "#3572A5",
    "JavaScript": "#f1e05a",
    "TypeScript": "#32a0ff",
    "Go": "#00dcdc",
    "Rust": "#dea584",
    "Java": "#b07219",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "Ruby": "#cc342d",
    "PHP": "#4F5D95",
    "Swift": "#F05138",
    "Kotlin": "#A97BFF",
    "Dart": "#00B4AB",
    "Shell": "#89e051",
    "Lua": "#000080",
    "Scala": "#c22d40",
    "R": "#198CE7",
    "Jupyter Notebook": "#f57c00",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
}
DEFAULT_COLOR = "#6b7280"


def load_galaxy_data():
    """Load all data files at startup from the unified/ directory."""
    global REPOS, POSITIONS, LEAF_LABELS, EDGE_SRC, EDGE_DST, EDGE_SIM
    global CLUSTER_TREE, CLUSTER_NODES, CLUSTER_NODE_MAP, REPO_NAME_TO_IDX
    global REPO_SHARD, REPO_SHARD_LINE

    meta_path = DATA_DIR / "meta_index.jsonl"
    starmap = DATA_DIR / "starmap"

    REPOS = []
    REPO_SHARD = []
    REPO_SHARD_LINE = []
    REPO_NAME_TO_IDX = {}

    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                repo = json.loads(line)
                REPO_NAME_TO_IDX[repo["full_name"].lower()] = len(REPOS)
                REPOS.append({
                    "full_name": repo["full_name"],
                    "stars": repo.get("stars", 0),
                    "description": repo.get("description", ""),
                    "language": repo.get("language", ""),
                    "html_url": repo.get("html_url", ""),
                    "created_month": repo.get("created_month", ""),
                })
                REPO_SHARD.append(repo.get("shard", ""))
                REPO_SHARD_LINE.append(repo.get("shard_line", -1))
            except Exception:
                REPOS.append({})
                REPO_SHARD.append("")
                REPO_SHARD_LINE.append(-1)

    print(f"  Galaxy: {len(REPOS):,} repos loaded from meta_index")

    # Positions (from starmap/)
    pos_path = starmap / "positions_3d.npy"
    if pos_path.exists():
        POSITIONS = np.load(str(pos_path))
        scale = 1000.0 / max(np.abs(POSITIONS).max(), 1.0)
        POSITIONS = (POSITIONS * scale).astype(np.float32)
        print(f"  Galaxy: positions loaded ({POSITIONS.shape})")

    # Leaf labels
    labels_path = starmap / "repo_leaf_labels.npy"
    if labels_path.exists():
        LEAF_LABELS = np.load(str(labels_path))
        print(f"  Galaxy: leaf labels loaded ({LEAF_LABELS.shape})")

    # Edges
    global HUB_INDICES
    edges_path = starmap / "galaxy_edges.npz"
    if edges_path.exists():
        edges = np.load(str(edges_path))
        EDGE_SRC = edges["src"]
        EDGE_DST = edges["dst"]
        EDGE_SIM = edges["sim"]
        print(f"  Galaxy: {len(EDGE_SRC):,} edges loaded")

        degree = np.zeros(len(REPOS), dtype=np.int32)
        np.add.at(degree, EDGE_SRC, 1)
        np.add.at(degree, EDGE_DST, 1)
        HUB_INDICES = np.where(degree >= 5)[0].tolist()
        print(f"  Galaxy: {len(HUB_INDICES):,} hub repos (degree >= 5)")

    # Cluster tree
    tree_path = starmap / "cluster_tree.json"
    if tree_path.exists():
        with open(tree_path) as f:
            CLUSTER_TREE = json.load(f)
        CLUSTER_NODES = CLUSTER_TREE.get("nodes", [])
        CLUSTER_NODE_MAP = {cn["id"]: cn for cn in CLUSTER_NODES}
        print(f"  Galaxy: {len(CLUSTER_NODES)} cluster nodes")


def _load_repo_detail(idx: int) -> dict:
    """Load full record from shard on-demand via shard path + line number."""
    if idx < 0 or idx >= len(REPO_SHARD):
        return {}
    shard_rel = REPO_SHARD[idx]
    shard_line = REPO_SHARD_LINE[idx]
    if not shard_rel or shard_line < 0:
        return {}
    shard_path = DATA_DIR / shard_rel
    try:
        with open(shard_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i == shard_line:
                    return json.loads(line)
    except Exception:
        pass
    return {}


def _make_node(idx: int, role: str = "cluster") -> dict:
    """Build a Galaxy node dict for a repo index."""
    repo = REPOS[idx] if idx < len(REPOS) else {}
    lang = repo.get("language", "")
    stars = repo.get("stars", 0)
    val = round(math.log2(max(stars, 1) + 1), 2)

    node = {
        "id": idx,
        "name": repo.get("full_name", f"repo_{idx}"),
        "stars": stars,
        "val": val,
        "color": LANG_COLORS.get(lang, DEFAULT_COLOR),
        "rawLang": lang or "Unknown",
        "cluster": "",
        "leafId": 0,
        "url": repo.get("html_url", ""),
        "role": role,
        "desc": repo.get("description", ""),
        "wiki": repo.get("wiki_snippet", ""),
    }

    # Add position if available
    if POSITIONS is not None and idx < len(POSITIONS):
        pos = POSITIONS[idx]
        node["x"] = round(float(pos[0]), 1)
        node["y"] = round(float(pos[1]), 1)
        node["z"] = round(float(pos[2]), 1)

    # Add cluster info
    if LEAF_LABELS is not None and idx < len(LEAF_LABELS):
        leaf_id = int(LEAF_LABELS[idx])
        node["leafId"] = leaf_id
        cn = CLUSTER_NODE_MAP.get(leaf_id)
        if cn:
            node["cluster"] = cn.get("name", "")

    return node


def resolve_focus_idx(node: str | None, id: int | None, random: bool) -> int | None:
    """Resolve a focus node index from various inputs."""
    if id is not None:
        return id if 0 <= id < len(REPOS) else None

    if node:
        key = node.strip().lower()
        idx = REPO_NAME_TO_IDX.get(key)
        if idx is not None:
            return idx
        # Partial match
        for name, i in REPO_NAME_TO_IDX.items():
            if key in name:
                return i
        return None

    if random:
        if HUB_INDICES:
            return rnd.choice(HUB_INDICES)
        return rnd.randint(0, len(REPOS) - 1)

    return None


def get_subgraph(focus_idx: int, max_nodes: int = 300) -> dict:
    """Get a subgraph around a focus node."""
    if focus_idx < 0 or focus_idx >= len(REPOS):
        return {"detail": "Invalid focus index"}

    focus_repo = REPOS[focus_idx]

    # Find the leaf cluster of the focus node
    leaf_id = 0
    if LEAF_LABELS is not None and focus_idx < len(LEAF_LABELS):
        leaf_id = int(LEAF_LABELS[focus_idx])

    cluster_name = ""
    cluster_size = 0
    parent_cluster_id = None

    cn = CLUSTER_NODE_MAP.get(leaf_id)
    if cn:
        cluster_name = cn.get("name", "")
        cluster_size = cn.get("size", 0)
        parent_cluster_id = cn.get("parent_id")

    # Collect nodes in the same leaf cluster
    cluster_indices = set()
    if LEAF_LABELS is not None:
        mask = LEAF_LABELS == leaf_id
        cluster_indices = set(np.where(mask)[0].tolist())

    # If cluster is too small, expand to parent
    if len(cluster_indices) < 10 and parent_cluster_id is not None:
        # Find all leaf clusters under parent
        child_leaf_ids = set()
        for cn in CLUSTER_NODES:
            if cn.get("parent_id") == parent_cluster_id or cn.get("id") == parent_cluster_id:
                if cn.get("is_leaf"):
                    child_leaf_ids.add(cn["id"])
        if LEAF_LABELS is not None:
            for lid in child_leaf_ids:
                mask = LEAF_LABELS == lid
                cluster_indices.update(np.where(mask)[0].tolist())

    # Ensure focus is included
    cluster_indices.add(focus_idx)

    # Pull in the focus node's top global neighbors so it always has visible edges
    if EDGE_SRC is not None:
        focus_neighbors = []
        mask_src = EDGE_SRC == focus_idx
        mask_dst = EDGE_DST == focus_idx
        for i in np.where(mask_src)[0]:
            focus_neighbors.append((int(EDGE_DST[i]), float(EDGE_SIM[i])))
        for i in np.where(mask_dst)[0]:
            focus_neighbors.append((int(EDGE_SRC[i]), float(EDGE_SIM[i])))
        focus_neighbors.sort(key=lambda x: -x[1])
        for neighbor_idx, _ in focus_neighbors[:20]:
            cluster_indices.add(neighbor_idx)

    # Limit to max_nodes (keep focus + random sample)
    indices = list(cluster_indices)
    if len(indices) > max_nodes:
        indices.remove(focus_idx)
        indices = [focus_idx] + rnd.sample(indices, max_nodes - 1)

    idx_set = set(indices)

    # Build nodes
    nodes = []
    for idx in indices:
        role = "focus" if idx == focus_idx else "cluster"
        nodes.append(_make_node(idx, role))

    # Build links (edges between nodes in the subgraph)
    links = []
    if EDGE_SRC is not None:
        for i in range(len(EDGE_SRC)):
            s, d = int(EDGE_SRC[i]), int(EDGE_DST[i])
            if s in idx_set and d in idx_set:
                links.append({
                    "source": s,
                    "target": d,
                    "sim": round(float(EDGE_SIM[i]), 4),
                })

    # Build ancestors
    ancestors = _get_ancestors(leaf_id)

    # Build siblings
    siblings = _get_siblings(leaf_id)

    return {
        "focus": focus_idx,
        "focusName": focus_repo.get("full_name", ""),
        "clusterName": cluster_name,
        "clusterSize": cluster_size,
        "leafId": leaf_id,
        "parentClusterId": parent_cluster_id,
        "ancestors": ancestors,
        "siblings": siblings,
        "nodes": nodes,
        "links": links,
        "totalRepos": len(REPOS),
    }


def _get_ancestors(leaf_id: int) -> list[dict]:
    """Get ancestor chain from root to the leaf's parent."""
    ancestors = []
    current = CLUSTER_NODE_MAP.get(leaf_id)
    if not current:
        return ancestors

    visited = set()
    while current.get("parent_id") is not None:
        pid = current["parent_id"]
        if pid in visited:
            break
        parent = CLUSTER_NODE_MAP.get(pid)
        if not parent:
            break
        visited.add(pid)
        ancestors.append({
            "id": parent["id"],
            "name": parent.get("name", ""),
            "size": parent.get("size", 0),
            "is_leaf": parent.get("is_leaf", False),
        })
        current = parent

    ancestors.reverse()
    return ancestors


def _get_siblings(leaf_id: int) -> list[dict]:
    """Get sibling clusters (same parent)."""
    cn = CLUSTER_NODE_MAP.get(leaf_id)
    if not cn:
        return []

    parent_id = cn.get("parent_id")
    if parent_id is None:
        return []

    siblings = []
    for cn in CLUSTER_NODES:
        if cn.get("parent_id") == parent_id:
            siblings.append({
                "id": cn["id"],
                "name": cn.get("name", ""),
                "size": cn.get("size", 0),
                "is_leaf": cn.get("is_leaf", False),
                "is_current": cn["id"] == leaf_id,
            })
    return siblings


def search_by_name(query: str, limit: int = 12) -> list[dict]:
    """Search Galaxy nodes by name prefix/substring."""
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    candidates = []
    for idx, repo in enumerate(REPOS):
        name = repo.get("full_name", "").lower()
        if query_lower in name:
            candidates.append(idx)

    # Sort by relevance: exact match first, then prefix, then by stars
    def _sort_key(idx: int):
        name = REPOS[idx].get("full_name", "").lower()
        if name == query_lower:
            tier = 0
        elif name.startswith(query_lower) or name.split("/")[-1] == query_lower:
            tier = 1
        elif name.split("/")[-1].startswith(query_lower):
            tier = 2
        else:
            tier = 3
        return (tier, -REPOS[idx].get("stars", 0))

    candidates.sort(key=_sort_key)

    results = []
    for idx in candidates[:limit]:
        node = _make_node(idx)
        edge_count = 0
        if EDGE_SRC is not None:
            edge_count = int(np.sum(EDGE_SRC == idx) + np.sum(EDGE_DST == idx))
        node["edgeCount"] = edge_count
        results.append(node)

    return results


def get_neighbors(idx: int, limit: int = 15) -> dict:
    """Return a node's top global neighbors as full Galaxy nodes + edges."""
    if idx < 0 or idx >= len(REPOS) or EDGE_SRC is None:
        return {"nodes": [], "links": []}

    mask_src = EDGE_SRC == idx
    mask_dst = EDGE_DST == idx

    neighbor_sims: list[tuple[int, float]] = []
    for i in np.where(mask_src)[0]:
        neighbor_sims.append((int(EDGE_DST[i]), float(EDGE_SIM[i])))
    for i in np.where(mask_dst)[0]:
        neighbor_sims.append((int(EDGE_SRC[i]), float(EDGE_SIM[i])))

    neighbor_sims.sort(key=lambda x: -x[1])
    top = neighbor_sims[:limit]

    nodes = [_make_node(n_idx, "neighbor") for n_idx, _ in top]
    links = [{"source": idx, "target": n_idx, "sim": round(sim, 4)} for n_idx, sim in top]

    return {"nodes": nodes, "links": links}


def _load_wiki_text(idx: int) -> str:
    """Load full wiki text from shard's deepwiki_text field on-demand."""
    detail = _load_repo_detail(idx)
    return (detail.get("deepwiki_text") or "").strip()


def get_node_detail(idx: int) -> dict:
    """Get detailed info for a single node."""
    if idx < 0 or idx >= len(REPOS):
        return {"id": idx, "name": "", "description": "", "wiki_text": "", "tree_text": "", "readme": "", "connections": []}

    detail = _load_repo_detail(idx)
    repo = REPOS[idx]

    # Get connections (edges)
    connections = []
    if EDGE_SRC is not None:
        # Find all edges involving this node
        mask_src = EDGE_SRC == idx
        mask_dst = EDGE_DST == idx

        for i in np.where(mask_src)[0]:
            neighbor = int(EDGE_DST[i])
            if neighbor < len(REPOS):
                nr = REPOS[neighbor]
                connections.append({
                    "id": neighbor,
                    "name": nr.get("full_name", ""),
                    "stars": nr.get("stars", 0),
                    "sim": round(float(EDGE_SIM[i]), 4),
                })

        for i in np.where(mask_dst)[0]:
            neighbor = int(EDGE_SRC[i])
            if neighbor < len(REPOS):
                nr = REPOS[neighbor]
                connections.append({
                    "id": neighbor,
                    "name": nr.get("full_name", ""),
                    "stars": nr.get("stars", 0),
                    "sim": round(float(EDGE_SIM[i]), 4),
                })

    # Sort by similarity
    connections.sort(key=lambda c: -c["sim"])

    return {
        "id": idx,
        "name": repo.get("full_name", ""),
        "description": repo.get("description", ""),
        "wiki_text": _load_wiki_text(idx),
        "tree_text": detail.get("tree_text", ""),
        "readme": detail.get("readme", ""),
        "connections": connections[:20],
    }


def get_cluster_subgraph(cluster_id: int, focus_id: int | None = None, max_nodes: int = 300) -> dict:
    """Get subgraph for a specific cluster."""
    cn = CLUSTER_NODE_MAP.get(cluster_id)
    if not cn:
        return {"detail": "Invalid cluster ID"}

    # Find all repos in this cluster
    if cn.get("is_leaf"):
        if LEAF_LABELS is not None:
            mask = LEAF_LABELS == cluster_id
            indices = np.where(mask)[0].tolist()
        else:
            indices = []
    else:
        # Non-leaf: collect all descendants
        leaf_ids = _get_descendant_leaves(cluster_id)
        indices = []
        if LEAF_LABELS is not None:
            for lid in leaf_ids:
                mask = LEAF_LABELS == lid
                indices.extend(np.where(mask)[0].tolist())

    if not indices:
        return {"detail": "Empty cluster"}

    # Determine focus
    if focus_id is not None and focus_id in set(indices):
        f_idx = focus_id
    else:
        # Pick the highest-star repo as focus
        f_idx = max(indices, key=lambda i: REPOS[i].get("stars", 0) if i < len(REPOS) else 0)

    # Limit
    if len(indices) > max_nodes:
        idx_set = set(indices)
        if f_idx in idx_set:
            idx_set.remove(f_idx)
        indices = [f_idx] + rnd.sample(list(idx_set), max_nodes - 1)

    return get_subgraph(f_idx, max_nodes)


def _get_descendant_leaves(cluster_id: int) -> list[int]:
    """Recursively find all leaf cluster IDs under a cluster."""
    leaves = []
    for cn in CLUSTER_NODES:
        if cn.get("parent_id") == cluster_id:
            if cn.get("is_leaf"):
                leaves.append(cn["id"])
            else:
                leaves.extend(_get_descendant_leaves(cn["id"]))
    return leaves


def expand_to_parent(idx: int, max_nodes: int = 300) -> dict:
    """Expand from a node to its parent cluster's subgraph."""
    if LEAF_LABELS is None or idx >= len(LEAF_LABELS):
        return get_subgraph(idx, max_nodes)

    leaf_id = int(LEAF_LABELS[idx])
    cn = CLUSTER_NODE_MAP.get(leaf_id)
    if not cn:
        return get_subgraph(idx, max_nodes)

    parent_id = cn.get("parent_id")
    if parent_id is None:
        return get_subgraph(idx, max_nodes)

    return get_cluster_subgraph(parent_id, focus_id=idx, max_nodes=max_nodes)
