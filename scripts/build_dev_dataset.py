#!/usr/bin/env python3
"""
Build a dev dataset from 10 selected leaf clusters.
Produces self-contained data files with remapped indices.
"""
import json, sys, time
import numpy as np
from pathlib import Path
from collections import defaultdict

DATA = Path("/data/workspace/code/github_repos/project/git-arsenal/packages/api/data")
DEV_DIR = DATA / "dev"
DEV_DIR.mkdir(exist_ok=True)

SELECTED_LEAVES = {575, 576, 584, 585, 1478, 1479, 1536, 1537, 1651, 1652}


def main():
    print("=== Building dev dataset ===")

    # Load labels to identify which repos are in selected leaves
    labels = np.load(DATA / "repo_leaf_labels.npy")
    N_total = len(labels)

    # old_idx -> True if in selected leaves
    keep_mask = np.array([int(labels[i]) in SELECTED_LEAVES for i in range(N_total)])
    old_indices = np.where(keep_mask)[0]
    N_dev = len(old_indices)
    print(f"Selected {N_dev} repos from {len(SELECTED_LEAVES)} leaves (out of {N_total})")

    # Build old->new index mapping
    old_to_new = {}
    for new_idx, old_idx in enumerate(old_indices):
        old_to_new[old_idx] = new_idx

    # 1. repos_meta.jsonl - filter and rewrite
    print("\n1. Filtering repos_meta.jsonl...")
    keep_set = set(old_indices.tolist())
    meta_out = DEV_DIR / "repos_meta.jsonl"
    count = 0
    with open(DATA / "repos_meta.jsonl", "r", encoding="utf-8") as fin, \
         open(meta_out, "w", encoding="utf-8") as fout:
        idx = 0
        for line in fin:
            if not line.strip():
                continue
            if idx in keep_set:
                fout.write(line)
                count += 1
            idx += 1
    print(f"   {count} repos written")

    # 2. embeddings.npy
    print("2. Filtering embeddings.npy...")
    emb = np.load(DATA / "embeddings.npy")
    dev_emb = emb[old_indices]
    np.save(DEV_DIR / "embeddings.npy", dev_emb)
    print(f"   shape: {dev_emb.shape}")
    del emb

    # 3. wiki_embeddings.npy
    print("3. Filtering wiki_embeddings.npy...")
    wiki_emb = np.load(DATA / "wiki_embeddings.npy")
    dev_wiki_emb = wiki_emb[old_indices]
    np.save(DEV_DIR / "wiki_embeddings.npy", dev_wiki_emb)
    print(f"   shape: {dev_wiki_emb.shape}")
    del wiki_emb

    # 4. wiki_texts.jsonl
    print("4. Filtering wiki_texts.jsonl...")
    wiki_out = DEV_DIR / "wiki_texts.jsonl"
    wcount = 0
    with open(DATA / "wiki_texts.jsonl", "r", encoding="utf-8") as fin, \
         open(wiki_out, "w", encoding="utf-8") as fout:
        idx = 0
        for line in fin:
            if not line.strip():
                continue
            if idx in keep_set:
                fout.write(line)
                wcount += 1
            idx += 1
    print(f"   {wcount} lines written")

    # 5. galaxy_edges.npz - filter edges where BOTH ends are in dev, remap indices
    print("5. Filtering galaxy_edges.npz...")
    edges = np.load(DATA / "galaxy_edges.npz")
    src_old, dst_old, sim_old = edges["src"], edges["dst"], edges["sim"]
    new_src, new_dst, new_sim = [], [], []
    for i in range(len(src_old)):
        s, d = int(src_old[i]), int(dst_old[i])
        if s in old_to_new and d in old_to_new:
            new_src.append(old_to_new[s])
            new_dst.append(old_to_new[d])
            new_sim.append(float(sim_old[i]))
    np.savez_compressed(DEV_DIR / "galaxy_edges.npz",
                        src=np.array(new_src, dtype=np.int32),
                        dst=np.array(new_dst, dtype=np.int32),
                        sim=np.array(new_sim, dtype=np.float32))
    print(f"   {len(new_src)} edges (remapped)")

    # 6. repo_leaf_labels.npy - remap
    print("6. Building repo_leaf_labels.npy...")
    dev_labels = labels[old_indices]
    np.save(DEV_DIR / "repo_leaf_labels.npy", dev_labels)
    print(f"   shape: {dev_labels.shape}, unique leaves: {len(set(dev_labels.tolist()))}")

    # 7. positions_3d.npy
    print("7. Filtering positions_3d.npy...")
    pos = np.load(DATA / "positions_3d.npy")
    dev_pos = pos[old_indices]
    np.save(DEV_DIR / "positions_3d.npy", dev_pos)
    print(f"   shape: {dev_pos.shape}")

    # 8. cluster_tree.json - rebuild for dev leaves only
    print("8. Building cluster_tree.json...")
    with open(DATA / "cluster_tree.json") as f:
        tree = json.load(f)

    # Find all ancestor nodes of selected leaves
    node_map = {n["id"]: n for n in tree["nodes"]}
    needed_ids = set()
    for lid in SELECTED_LEAVES:
        curr = lid
        while curr is not None:
            needed_ids.add(curr)
            curr = node_map[curr].get("parent_id")

    # Filter nodes, update sizes
    dev_nodes = []
    for n in tree["nodes"]:
        if n["id"] not in needed_ids:
            continue
        node_copy = dict(n)
        node_copy["children_ids"] = [cid for cid in n.get("children_ids", []) if cid in needed_ids]
        if n["is_leaf"]:
            node_copy["size"] = sum(1 for i in old_indices if int(labels[i]) == n["id"])
        else:
            node_copy["size"] = sum(
                next((nn["size"] for nn in dev_nodes if nn["id"] == cid), 0)
                for cid in node_copy["children_ids"]
            ) if node_copy["children_ids"] else 0
        dev_nodes.append(node_copy)

    # Recount sizes from bottom up
    id_to_node = {n["id"]: n for n in dev_nodes}
    for n in reversed(dev_nodes):
        if not n["is_leaf"] and n["children_ids"]:
            n["size"] = sum(id_to_node[cid]["size"] for cid in n["children_ids"] if cid in id_to_node)

    dev_tree = {
        "target_leaf_size": tree.get("target_leaf_size", 150),
        "total_repos": N_dev,
        "total_nodes": len(dev_nodes),
        "leaf_count": len(SELECTED_LEAVES),
        "max_depth": max(n["depth"] for n in dev_nodes),
        "nodes": dev_nodes,
    }

    class NE(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, (np.integer,)): return int(o)
            if isinstance(o, (np.floating,)): return float(o)
            if isinstance(o, np.ndarray): return o.tolist()
            return super().default(o)

    with open(DEV_DIR / "cluster_tree.json", "w") as f:
        json.dump(dev_tree, f, ensure_ascii=False, indent=1, cls=NE)
    print(f"   {len(dev_nodes)} nodes, {len(SELECTED_LEAVES)} leaves")

    # Summary
    print(f"\n{'='*60}")
    print(f"Dev dataset ready at {DEV_DIR}")
    print(f"  Repos: {N_dev}")
    print(f"  Edges: {len(new_src)}")
    print(f"  Leaves: {len(SELECTED_LEAVES)}")
    for p in sorted(DEV_DIR.iterdir()):
        sz = p.stat().st_size
        if sz > 1024 * 1024:
            print(f"  {p.name:30s} {sz/1024/1024:.1f} MB")
        else:
            print(f"  {p.name:30s} {sz/1024:.0f} KB")


if __name__ == "__main__":
    main()
