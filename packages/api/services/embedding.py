"""
Embedding service — wraps DashScope / OpenAI-compatible embedding API.

Features:
  - Configurable timeout (EMBED_TIMEOUT)
  - Automatic retry (EMBED_MAX_RETRIES) with exponential backoff
  - Clear error propagation (EmbeddingError) for caller to handle
"""
import time
from openai import OpenAI
from config import EMBED_API_KEY, EMBED_BASE_URL, EMBED_MODEL, EMBED_DIM, EMBED_TIMEOUT, EMBED_MAX_RETRIES

_client: OpenAI | None = None


class EmbeddingError(Exception):
    """Raised when embedding generation fails after all retries."""
    pass


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=EMBED_API_KEY,
            base_url=EMBED_BASE_URL,
            timeout=EMBED_TIMEOUT,
        )
    return _client


def get_embedding(text: str) -> list[float]:
    """
    Generate a single embedding vector (synchronous, call in thread pool).

    Retries up to EMBED_MAX_RETRIES times on failure.
    Raises EmbeddingError if all retries exhausted.
    """
    client = _get_client()
    last_error = None

    for attempt in range(EMBED_MAX_RETRIES + 1):
        try:
            resp = client.embeddings.create(
                model=EMBED_MODEL,
                input=text,
                dimensions=EMBED_DIM,
            )
            return resp.data[0].embedding
        except Exception as e:
            last_error = e
            if attempt < EMBED_MAX_RETRIES:
                wait = 2 ** attempt
                print(f"⚠️ Embedding attempt {attempt + 1} failed ({type(e).__name__}), retrying in {wait}s...")
                time.sleep(wait)

    raise EmbeddingError(f"Embedding failed after {EMBED_MAX_RETRIES + 1} attempts: {last_error}")