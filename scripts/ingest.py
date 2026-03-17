"""
Ingest repos data into Qdrant vector database.

Supports dual named vectors (tree + wiki) for multi-recall search.
Wiki vectors are only stored for repos with real DeepWiki content (>=300 chars),
not short GitHub description fallbacks.

Usage:
    python scripts/ingest.py [--data-dir PATH] [--force] [--wiki-min-len 300]
"""
import sys
import json
import argparse
import time
from pathlib import Path

import numpy as np

api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from config import QDRANT_URL, QDRANT_COLLECTION, EMBED_DIM, DATA_DIR

WIKI_MIN_LEN = 300


def main():
    parser = argparse.ArgumentParser(description="Ingest repo data into Qdrant")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(DATA_DIR),
    )
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--wiki-min-len", type=int, default=WIKI_MIN_LEN,
                        help="Min wiki_text length to include wiki vector (skip short fallbacks)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    meta_file = data_dir / "repos_meta.jsonl"
    tree_emb_file = data_dir / "embeddings.npy"
    wiki_emb_file = data_dir / "wiki_embeddings.npy"
    wiki_text_file = data_dir / "wiki_texts.jsonl"

    for f in [meta_file, tree_emb_file]:
        if not f.exists():
            print(f"Error: {f} not found")
            sys.exit(1)

    has_wiki = wiki_emb_file.exists()
    if not has_wiki:
        print(f"Warning: {wiki_emb_file} not found, ingesting tree vectors only")

    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=QDRANT_URL, timeout=120)

    # --- Pre-scan wiki texts to build valid-index set ---
    valid_wiki_idxs: set[int] = set()
    wiki_texts_payload: dict[int, str] = {}
    if wiki_text_file.exists():
        with open(wiki_text_file, "r") as f:
            for idx, line in enumerate(f):
                try:
                    obj = json.loads(line)
                    wt = (obj.get("wiki_text") or "").strip()
                    if len(wt) >= args.wiki_min_len:
                        valid_wiki_idxs.add(idx)
                        wiki_texts_payload[idx] = wt
                except Exception:
                    pass
        print(f"Wiki texts: {len(valid_wiki_idxs):,} valid (>={args.wiki_min_len} chars)")

    # --- Recreate collection ---
    collections = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION in collections:
        info = client.get_collection(QDRANT_COLLECTION)
        print(f"Collection '{QDRANT_COLLECTION}' exists with {info.points_count} points")
        if not args.force:
            resp = input("Delete and re-create? [y/N]: ").strip().lower()
            if resp != "y":
                print("Aborted.")
                return
        client.delete_collection(QDRANT_COLLECTION)
        print("Deleted old collection.")

    vectors_config = {
        "tree": models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE),
    }
    if has_wiki and valid_wiki_idxs:
        vectors_config["wiki"] = models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE)
    vector_names = list(vectors_config.keys())

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=vectors_config,
    )
    print(f"Created collection '{QDRANT_COLLECTION}' with vectors: {vector_names}")

    # --- Load embeddings ---
    tree_embeddings = np.load(str(tree_emb_file))
    print(f"Tree embeddings: {tree_embeddings.shape}")

    wiki_embeddings = None
    if has_wiki and "wiki" in vectors_config:
        wiki_embeddings = np.load(str(wiki_emb_file))
        print(f"Wiki embeddings: {wiki_embeddings.shape}")

    # --- Batch upsert ---
    batch_size = 200
    max_text_payload = 2000  # truncate long text payloads to avoid 32MB limit
    points: list = []
    count = 0
    wiki_count = 0
    t_start = time.time()

    with open(meta_file) as f:
        for idx, line in enumerate(f):
            try:
                repo = json.loads(line)
            except Exception:
                continue
            if idx >= len(tree_embeddings):
                break

            tree_vec = tree_embeddings[idx].tolist()
            vector: dict = {"tree": tree_vec}

            if wiki_embeddings is not None and idx in valid_wiki_idxs:
                wv = wiki_embeddings[idx]
                if np.any(wv != 0):
                    vector["wiki"] = wv.tolist()
                    wiki_count += 1

            tree_text = repo.get("tree_text", "")
            if len(tree_text) > max_text_payload:
                tree_text = tree_text[:max_text_payload]

            payload = {
                "full_name": repo.get("full_name", ""),
                "stars": repo.get("stars", 0),
                "language": repo.get("language", ""),
                "description": repo.get("description", ""),
                "html_url": repo.get("html_url", ""),
                "tree_text": tree_text,
            }
            if idx in wiki_texts_payload:
                wt = wiki_texts_payload[idx]
                payload["wiki_text"] = wt[:max_text_payload] if len(wt) > max_text_payload else wt

            points.append(models.PointStruct(id=idx, vector=vector, payload=payload))

            if len(points) >= batch_size:
                client.upsert(collection_name=QDRANT_COLLECTION, points=points)
                count += len(points)
                elapsed = time.time() - t_start
                rate = count / elapsed if elapsed > 0 else 0
                eta = (len(tree_embeddings) - count) / rate if rate > 0 else 0
                print(f"  {count:,} / {len(tree_embeddings):,} points  "
                      f"({wiki_count:,} wiki)  {rate:.0f} pts/s  ETA {eta:.0f}s")
                points = []

    if points:
        client.upsert(collection_name=QDRANT_COLLECTION, points=points)
        count += len(points)

    elapsed = time.time() - t_start
    print(f"Ingested {count:,} points ({wiki_count:,} with wiki vector) in {elapsed:.1f}s")

    # --- Create payload indexes ---
    print("Creating indexes...")
    client.create_payload_index(
        collection_name=QDRANT_COLLECTION,
        field_name="full_name",
        field_schema=models.TextIndexParams(
            type="text",
            tokenizer=models.TokenizerType.WORD,
            lowercase=True,
        ),
    )
    client.create_payload_index(
        collection_name=QDRANT_COLLECTION,
        field_name="language",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=QDRANT_COLLECTION,
        field_name="stars",
        field_schema=models.PayloadSchemaType.INTEGER,
    )
    print(f"Done! {count:,} points, {wiki_count:,} wiki vectors, 3 payload indexes.")


if __name__ == "__main__":
    main()
