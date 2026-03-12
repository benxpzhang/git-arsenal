"""
Galaxy visualization service — loads and serves 3D graph data.

Data files expected in DATA_DIR (packages/api/data/):
  - repos_meta.jsonl   -> lightweight repo metadata
  - galaxy_edges.npz   -> pre-computed kNN edges
  - positions_3d.npy   -> UMAP 3D coordinates (N, 3)
  - cluster_tree.json  -> hierarchical cluster tree
  - repo_leaf_labels.npy -> per-repo leaf cluster assignment
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
REPO_NAME_TO_IDX: dict[str, int] = {}
META_FILE_PATH: Path | None = None
REPO_OFFSETS: list[int] = []
HUB_INDICES: list[int] = []  # repos with >= 5 edges, used for random focus

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
    """Load all data files at startup."""
    global REPOS, POSITIONS, LEAF_LABELS, EDGE_SRC, EDGE_DST, EDGE_SIM
    global CLUSTER_TREE, CLUSTER_NODES, REPO_NAME_TO_IDX, META_FILE_PATH, REPO_OFFSETS

    meta_path = DATA_DIR / "repos_meta.jsonl"
    META_FILE_PATH = meta_path

    # Load lightweight metadata (line-by-line JSONL with byte offsets for on-demand detail)
    REPOS = []
    REPO_OFFSETS = []
    REPO_NAME_TO_IDX = {}
    with open(meta_path, "r") as f:
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break
            try:
                repo = json.loads(line)
                REPO_OFFSETS.append(offset)
                REPO_NAME_TO_IDX[repo["full_name"].lower()] = len(REPOS)
                REPOS.append({
                    "full_name": repo["full_name"],
                    "stars": repo.get("stars", 0),
                    "description": repo.get("description", ""),
                    "language": repo.get("language", ""),
                    "html_url": repo.get("html_url", ""),
                })
            except Exception:
                REPO_OFFSETS.append(offset)
                REPOS.append({})

    print(f"  Galaxy: {len(REPOS):,} repos loaded")

    # Positions
    pos_path = DATA_DIR / "positions_3d.npy"
    if pos_path.exists():
        POSITIONS = np.load(str(pos_path))
        # Scale to reasonable range
        scale = 1000.0 / max(np.abs(POSITIONS).max(), 1.0)
        POSITIONS = (POSITIONS * scale).astype(np.float32)
        print(f"  Galaxy: positions loaded ({POSITIONS.shape})")

    # Leaf labels
    labels_path = DATA_DIR / "repo_leaf_labels.npy"
    if labels_path.exists():
        LEAF_LABELS = np.load(str(labels_path))
        print(f"  Galaxy: leaf labels loaded ({LEAF_LABELS.shape})")

    # Edges
    global HUB_INDICES
    edges_path = DATA_DIR / "galaxy_edges.npz"
    if edges_path.exists():
        edges = np.load(str(edges_path))
        EDGE_SRC = edges["src"]
        EDGE_DST = edges["dst"]
        EDGE_SIM = edges["sim"]
        print(f"  Galaxy: {len(EDGE_SRC):,} edges loaded")

        # Pre-compute hub repos (>= 5 edges) for better random focus
        degree = np.zeros(len(REPOS), dtype=np.int32)
        np.add.at(degree, EDGE_SRC, 1)
        np.add.at(degree, EDGE_DST, 1)
        HUB_INDICES = np.where(degree >= 5)[0].tolist()
        print(f"  Galaxy: {len(HUB_INDICES):,} hub repos (degree >= 5)")

    # Cluster tree
    tree_path = DATA_DIR / "cluster_tree.json"
    if tree_path.exists():
        with open(tree_path) as f:
            CLUSTER_TREE = json.load(f)
        CLUSTER_NODES = CLUSTER_TREE.get("nodes", [])
        print(f"  Galaxy: {len(CLUSTER_NODES)} cluster nodes")


def _load_repo_detail(idx: int) -> dict:
    """Load full record (with tree_text, readme) from disk on-demand."""
    if idx < 0 or idx >= len(REPO_OFFSETS) or META_FILE_PATH is None:
        return {}
    offset = REPO_OFFSETS[idx]
    try:
        with open(META_FILE_PATH, "r") as f:
            f.seek(offset)
            line = f.readline()
            return json.loads(line)
    except Exception:
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
        if leaf_id < len(CLUSTER_NODES):
            node["cluster"] = CLUSTER_NODES[leaf_id].get("name", "")

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

    if leaf_id < len(CLUSTER_NODES):
        cn = CLUSTER_NODES[leaf_id]
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
    if not CLUSTER_NODES or leaf_id >= len(CLUSTER_NODES):
        return ancestors

    # Walk up the tree
    current = CLUSTER_NODES[leaf_id]
    visited = set()
    while current.get("parent_id") is not None:
        pid = current["parent_id"]
        if pid in visited or pid >= len(CLUSTER_NODES):
            break
        visited.add(pid)
        parent = CLUSTER_NODES[pid]
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
    if not CLUSTER_NODES or leaf_id >= len(CLUSTER_NODES):
        return []

    parent_id = CLUSTER_NODES[leaf_id].get("parent_id")
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

    results = []
    for idx, repo in enumerate(REPOS):
        name = repo.get("full_name", "").lower()
        if query_lower in name:
            node = _make_node(idx)
            # Add edgeCount
            edge_count = 0
            if EDGE_SRC is not None:
                edge_count = int(np.sum(EDGE_SRC == idx) + np.sum(EDGE_DST == idx))
            node["edgeCount"] = edge_count
            results.append(node)
            if len(results) >= limit:
                break

    # Sort by relevance: exact match first, then by stars
    results.sort(key=lambda n: (
        0 if n["name"].lower() == query_lower else (
            1 if n["name"].lower().startswith(query_lower) else 2
        ),
        -n["stars"],
    ))

    return results[:limit]


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


def get_node_detail(idx: int) -> dict:
    """Get detailed info for a single node."""
    if idx < 0 or idx >= len(REPOS):
        return {"id": idx, "name": "", "description": "", "tree_text": "", "readme": "", "connections": []}

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
        "tree_text": detail.get("tree_text", ""),
        "readme": detail.get("readme", ""),
        "connections": connections[:20],
    }


def get_cluster_subgraph(cluster_id: int, focus_id: int | None = None, max_nodes: int = 300) -> dict:
    """Get subgraph for a specific cluster."""
    if cluster_id >= len(CLUSTER_NODES):
        return {"detail": "Invalid cluster ID"}

    cn = CLUSTER_NODES[cluster_id]

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
    if leaf_id >= len(CLUSTER_NODES):
        return get_subgraph(idx, max_nodes)

    parent_id = CLUSTER_NODES[leaf_id].get("parent_id")
    if parent_id is None:
        return get_subgraph(idx, max_nodes)

    return get_cluster_subgraph(parent_id, focus_id=idx, max_nodes=max_nodes)
