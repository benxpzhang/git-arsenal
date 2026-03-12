"""
Ingest repos data into Qdrant vector database.

Usage:
    python scripts/ingest.py [--data-dir PATH]
"""
import sys
import json
import argparse
from pathlib import Path

# Add API package to path
api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from config import QDRANT_URL, QDRANT_COLLECTION, EMBED_DIM


def main():
    parser = argparse.ArgumentParser(description="Ingest repo data into Qdrant")
    parser.add_argument(
        "--data-dir",
        type=str,
        default=str(Path(__file__).resolve().parent.parent / "packages" / "api" / "data"),
        help="Path to data directory containing repos_meta.jsonl and embeddings",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    meta_file = data_dir / "repos_meta.jsonl"

    if not meta_file.exists():
        print(f"Error: {meta_file} not found")
        sys.exit(1)

    from qdrant_client import QdrantClient, models
    import numpy as np

    client = QdrantClient(url=QDRANT_URL, timeout=60)

    # Check if collection exists
    collections = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION in collections:
        info = client.get_collection(QDRANT_COLLECTION)
        print(f"Collection '{QDRANT_COLLECTION}' already exists with {info.points_count} points")
        resp = input("Delete and re-create? [y/N]: ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return
        client.delete_collection(QDRANT_COLLECTION)

    # Create collection
    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=models.VectorParams(size=EMBED_DIM, distance=models.Distance.COSINE),
    )
    print(f"Created collection '{QDRANT_COLLECTION}' with dim={EMBED_DIM}")

    # Load embeddings
    emb_file = data_dir / "embeddings.npy"
    if not emb_file.exists():
        print(f"Error: {emb_file} not found")
        sys.exit(1)

    embeddings = np.load(str(emb_file))
    print(f"Loaded embeddings: {embeddings.shape}")

    # Load metadata and upsert in batches
    batch_size = 500
    points = []
    count = 0

    with open(meta_file) as f:
        for idx, line in enumerate(f):
            try:
                repo = json.loads(line)
            except Exception:
                continue

            if idx >= len(embeddings):
                break

            vec = embeddings[idx].tolist()
            payload = {
                "full_name": repo.get("full_name", ""),
                "stars": repo.get("stars", 0),
                "language": repo.get("language", ""),
                "description": repo.get("description", ""),
                "html_url": repo.get("html_url", ""),
                "tree_text": repo.get("tree_text", ""),
            }

            points.append(models.PointStruct(id=idx, vector=vec, payload=payload))

            if len(points) >= batch_size:
                client.upsert(collection_name=QDRANT_COLLECTION, points=points)
                count += len(points)
                print(f"  Upserted {count:,} points...")
                points = []

    if points:
        client.upsert(collection_name=QDRANT_COLLECTION, points=points)
        count += len(points)

    print(f"Done! Total {count:,} points ingested.")


if __name__ == "__main__":
    main()
