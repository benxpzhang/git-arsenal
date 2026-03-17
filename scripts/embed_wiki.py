#!/usr/bin/env python3
"""
Batch-embed wiki texts using DashScope text-embedding-v4.

- Reads wiki_texts.jsonl (aligned with repos_meta.jsonl)
- Generates 1024-dim embeddings in batches
- Supports checkpoint/resume via partial .npy saves
- Outputs wiki_embeddings.npy

Usage:
    python scripts/embed_wiki.py [--limit 1000] [--batch-size 25] [--rps 10]
"""
import sys
import json
import time
import argparse
import numpy as np
from pathlib import Path

api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from openai import OpenAI
from config import EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL, EMBED_DIM


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=str,
                        default=str(Path(__file__).resolve().parent.parent / 'packages/api/data/wiki_texts.jsonl'))
    parser.add_argument('--output', type=str,
                        default=str(Path(__file__).resolve().parent.parent / 'packages/api/data/wiki_embeddings.npy'))
    parser.add_argument('--batch-size', type=int, default=10,
                        help='Texts per API call (DashScope max 10)')
    parser.add_argument('--rps', type=float, default=8,
                        help='Max API requests per second')
    parser.add_argument('--limit', type=int, default=0,
                        help='Only embed first N texts (0=all)')
    parser.add_argument('--checkpoint-interval', type=int, default=5000,
                        help='Save checkpoint every N texts')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    checkpoint_path = output_path.with_suffix('.checkpoint.npy')

    # Load texts
    print(f"Loading texts from {input_path}...")
    texts = []
    with open(input_path, 'r') as f:
        for line in f:
            obj = json.loads(line)
            texts.append(obj.get('wiki_text', '') or '')
    total = len(texts)
    if args.limit > 0:
        total = min(total, args.limit)
    print(f"  Total texts: {total:,}")

    # Check for checkpoint
    start_idx = 0
    if checkpoint_path.exists():
        existing = np.load(str(checkpoint_path))
        start_idx = len(existing)
        print(f"  Resuming from checkpoint: {start_idx:,} already embedded")
        embeddings = list(existing)
    else:
        embeddings = []

    if start_idx >= total:
        print("All texts already embedded.")
        if checkpoint_path.exists():
            arr = np.array(embeddings, dtype=np.float32)
            np.save(str(output_path), arr)
            print(f"Saved final: {output_path} ({arr.shape})")
        return

    client = OpenAI(api_key=EMBED_API_KEY, base_url=EMBED_BASE_URL, timeout=30)
    min_interval = 1.0 / args.rps

    non_empty_total = sum(1 for t in texts[start_idx:total] if (t or "").strip())
    est_calls = (non_empty_total + args.batch_size - 1) // args.batch_size if non_empty_total else 0
    print(f"Embedding with {EMBED_MODEL}, batch_size={args.batch_size}, rps={args.rps}")
    print(f"  Non-empty texts to embed: {non_empty_total:,}")
    print(f"  Estimated API calls: {est_calls:,}")

    processed = start_idx
    errors = 0
    skipped_empty = 0
    api_calls = 0
    start_time = time.time()
    last_report = start_time
    last_call = 0.0

    for batch_start in range(start_idx, total, args.batch_size):
        batch_end = min(batch_start + args.batch_size, total)
        batch_texts = texts[batch_start:batch_end]
        batch_embeddings = [[0.0] * EMBED_DIM for _ in batch_texts]
        request_indices = []
        request_texts = []
        for i, t in enumerate(batch_texts):
            if (t or "").strip():
                request_indices.append(i)
                request_texts.append(t)
            else:
                skipped_empty += 1

        if not request_texts:
            embeddings.extend(batch_embeddings)
            processed = batch_end
            continue

        # Rate limit
        now = time.time()
        elapsed_since_last = now - last_call
        if elapsed_since_last < min_interval:
            time.sleep(min_interval - elapsed_since_last)

        try:
            resp = client.embeddings.create(
                model=EMBED_MODEL,
                input=request_texts,
                dimensions=EMBED_DIM,
            )
            api_calls += 1
            last_call = time.time()

            api_batch_embeddings = [None] * len(request_texts)
            for item in resp.data:
                api_batch_embeddings[item.index] = item.embedding

            for i, emb in enumerate(api_batch_embeddings):
                if emb is None:
                    batch_embeddings[request_indices[i]] = [0.0] * EMBED_DIM
                    errors += 1
                else:
                    batch_embeddings[request_indices[i]] = emb

            embeddings.extend(batch_embeddings)

            processed = batch_end

        except Exception as e:
            print(f"  Error at batch {batch_start}: {type(e).__name__}: {e}")
            errors += len(request_texts)
            embeddings.extend(batch_embeddings)
            processed = batch_end
            time.sleep(2)

        now = time.time()
        if now - last_report >= 15:
            elapsed = now - start_time
            rate = (processed - start_idx) / elapsed if elapsed > 0 else 0
            eta_m = (total - processed) / rate / 60 if rate > 0 else 0
            print(f"  Progress: {processed:,}/{total:,} ({processed/total*100:.1f}%) "
                  f"| Rate: {rate:.1f}/s | API calls: {api_calls:,} "
                  f"| Empty skipped: {skipped_empty:,} | Errors: {errors} | ETA: {eta_m:.1f}m")
            last_report = now

        if processed % args.checkpoint_interval < args.batch_size and processed > start_idx:
            arr = np.array(embeddings, dtype=np.float32)
            np.save(str(checkpoint_path), arr)

    # Save final
    arr = np.array(embeddings, dtype=np.float32)
    np.save(str(output_path), arr)
    elapsed = time.time() - start_time
    print(f"\nDone! {processed:,} embeddings in {elapsed:.0f}s")
    print(f"  Shape: {arr.shape}, API calls: {api_calls:,}, Empty skipped: {skipped_empty:,}, Errors: {errors}")
    print(f"  Output: {output_path}")

    # Clean up checkpoint
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        print("  Checkpoint removed.")


if __name__ == '__main__':
    main()
