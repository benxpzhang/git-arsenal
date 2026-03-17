#!/usr/bin/env python3
"""Pick 10 leaf clusters with most edges for a dev dataset."""
import numpy as np, json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path("/data/workspace/code/github_repos/project/git-arsenal/packages/api/data")

labels = np.load(DATA / "repo_leaf_labels.npy")
edges = np.load(DATA / "galaxy_edges.npz")
src, dst, sim = edges["src"], edges["dst"], edges["sim"]

with open(DATA / "cluster_tree.json") as f:
    tree = json.load(f)

N = len(labels)
leaf_nodes = [n for n in tree["nodes"] if n["is_leaf"]]
print(f"Total repos: {N}, Leaves: {len(leaf_nodes)}, Edges: {len(src)}")

leaf_edge_count = Counter()
leaf_internal_edges = Counter()
for i in range(len(src)):
    s, d = int(src[i]), int(dst[i])
    ls, ld = int(labels[s]), int(labels[d])
    leaf_edge_count[ls] += 1
    leaf_edge_count[ld] += 1
    if ls == ld:
        leaf_internal_edges[ls] += 1

leaf_size = Counter()
for i in range(N):
    lid = int(labels[i])
    if lid >= 0:
        leaf_size[lid] += 1

cross_leaf = Counter()
for i in range(len(src)):
    s, d = int(src[i]), int(dst[i])
    ls, ld = int(labels[s]), int(labels[d])
    if ls != ld:
        pair = (min(ls, ld), max(ls, ld))
        cross_leaf[pair] += 1

leaf_name = {n["id"]: n["name"] for n in tree["nodes"]}

print("\nTop 30 leaves by total edge count:")
header = f"  {'Leaf':>6}  {'Size':>5}  {'Edges':>6}  {'Internal':>8}  Name"
print(header)
for lid, cnt in leaf_edge_count.most_common(30):
    name = leaf_name.get(lid, "?")
    print(f"  {lid:>6}  {leaf_size[lid]:>5}  {cnt:>6}  {leaf_internal_edges[lid]:>8}  {name}")

# Greedy pick: start with richest leaf, add neighbors with most cross-edges
print("\n=== Greedy selection of 10 connected leaf clusters ===")
selected = []
selected_set = set()

best = leaf_edge_count.most_common(1)[0][0]
selected.append(best)
selected_set.add(best)
print(f"  Start: leaf {best} (size={leaf_size[best]}, edges={leaf_edge_count[best]}, name={leaf_name.get(best, '?')})")

for step in range(9):
    best_score = -1
    best_cand = None
    for lid in leaf_edge_count:
        if lid in selected_set:
            continue
        score = 0
        for sel in selected_set:
            pair = (min(lid, sel), max(lid, sel))
            score += cross_leaf.get(pair, 0)
        if score > best_score:
            best_score = score
            best_cand = lid
    if best_cand is None or best_score == 0:
        # fallback: pick next by total edge count
        for lid, _ in leaf_edge_count.most_common():
            if lid not in selected_set:
                best_cand = lid
                best_score = 0
                break
    selected.append(best_cand)
    selected_set.add(best_cand)
    print(f"  +leaf {best_cand} (size={leaf_size[best_cand]}, cross_to_selected={best_score}, name={leaf_name.get(best_cand, '?')})")

total_repos = sum(leaf_size[lid] for lid in selected)
dev_edges = 0
for i in range(len(src)):
    s, d = int(src[i]), int(dst[i])
    if int(labels[s]) in selected_set and int(labels[d]) in selected_set:
        dev_edges += 1

print(f"\nSelected leaves: {sorted(selected)}")
print(f"Total repos: {total_repos}")
print(f"Edges within dev: {dev_edges}")

print("\nDetailed:")
for lid in selected:
    n = next(x for x in tree["nodes"] if x["id"] == lid)
    top = [f"{r[0]}({r[1]})" for r in n["top_repos"][:2]]
    print(f"  Leaf {lid:>4}: {leaf_size[lid]:>4} repos, {leaf_edge_count[lid]:>4} edges, {leaf_name[lid]}, top: {', '.join(top)}")
