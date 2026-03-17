"""
Unified query parser: one LLM call → keywords + hypothetical tree.

Used as fallback when the Agent doesn't provide these fields.
"""
import json
import re
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT

_client: OpenAI | None = None


def _get_client() -> OpenAI | None:
    global _client
    if _client is None:
        if not LLM_API_KEY:
            return None
        _client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=LLM_TIMEOUT)
    return _client


SYSTEM_PROMPT = """You are a GitHub open-source expert. Given a user query, output TWO things in a single JSON object:

1. "keywords": 5-10 real GitHub repo or org name fragments (lowercase) that match the query.
   - Focus on well-known, specific project names, NOT generic words.
   - e.g. "RAG platform" → ["dify","langchain","ragflow","llama-index","quivr","haystack"]

2. "tree": A hypothetical repo directory tree (max-depth 4, 60-120 lines) for the kind of project described.
   - First line: "project-name | N dirs | M files"
   - Use ├──/└──/│ connectors. Include .github/workflows/, src/, tests/, docs/, config files.
   - Filenames must be specific and domain-relevant.

Output ONLY the JSON object, no explanation. Example:

{"keywords":["firecrawl","scrapy","crawlee","playwright","crawl4ai"],"tree":"web-scraper | 60 dirs | 220 files\\n├── apps/\\n│   └── api/\\n│       ├── src/\\n│       │   ├── controllers/\\n│       │   │   ├── crawl.ts\\n│       │   │   └── scrape.ts\\n│       │   └── services/\\n│       │       ├── queue-worker.ts\\n│       │       └── html-to-markdown.ts\\n│       └── package.json\\n├── docker-compose.yml\\n└── README.md"}"""


def parse_query(query: str) -> tuple[list[str], str]:
    """
    Single LLM call to extract keywords + generate hypothetical tree.
    Returns (keywords, tree). Falls back gracefully on failure.
    """
    client = _get_client()
    if not client:
        return _fallback_keywords(query), query

    try:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=4096,
            temperature=0.3,
            timeout=max(LLM_TIMEOUT, 60),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        return _parse_response(content, query)
    except Exception as e:
        print(f"  QueryParser failed ({type(e).__name__}: {e})")
        return _fallback_keywords(query), query


def _parse_response(text: str, query: str) -> tuple[list[str], str]:
    """Parse the JSON response into (keywords, tree)."""
    text = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`')

    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                obj = json.loads(match.group())
            except json.JSONDecodeError:
                return _fallback_keywords(query), query
        else:
            return _fallback_keywords(query), query

    keywords = []
    if isinstance(obj.get("keywords"), list):
        keywords = [str(k).lower().strip() for k in obj["keywords"] if k and str(k).strip()]

    tree = query
    if isinstance(obj.get("tree"), str) and len(obj["tree"]) > 50:
        tree = obj["tree"]

    if not keywords:
        keywords = _fallback_keywords(query)

    print(f"  QueryParser: {len(keywords)} keywords, tree {len(tree)} chars")
    return keywords, tree


def _fallback_keywords(query: str) -> list[str]:
    stop_words = {"the", "a", "an", "for", "and", "or", "in", "on", "to", "of",
                  "is", "that", "with", "by", "best", "top", "good", "using"}
    words = re.findall(r'[a-zA-Z0-9]+', query.lower())
    return [w for w in words if len(w) >= 2 and w not in stop_words][:5]
