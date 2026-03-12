"""
HyDE (Hypothetical Document Embedding) service.

Generates a hypothetical GitHub repo directory tree from a user query,
which is then embedded and used for vector similarity search.

Fallback chain:
  LLM success -> hypothetical tree
  LLM timeout/error -> raw query (still works for embedding)
"""
from openai import OpenAI
from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT

_llm_client: OpenAI | None = None


def _get_llm_client() -> OpenAI | None:
    global _llm_client
    if _llm_client is None:
        if not LLM_API_KEY:
            return None
        _llm_client = OpenAI(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            timeout=LLM_TIMEOUT,
        )
    return _llm_client


HYDE_SYSTEM_PROMPT = """你是一个 GitHub 项目架构师。用户会描述一个项目需求，你需要为这个需求生成一个假想的 GitHub 仓库目录结构（repo tree）。

要求：
1. 输出格式必须严格按照以下示例，第一行是 "项目名 | N dirs | M files"，然后是树形结构
2. 目录结构要合理、真实，包含主要的源码目录、配置文件、文档等
3. 文件名要具体、有意义，能体现项目的功能
4. 不要输出任何解释，只输出目录结构
5. 控制在 20-40 行以内

示例输出：
stock-quant-trader | 25 dirs | 80 files
├── src/
│   ├── strategy/
│   │   ├── momentum.py
│   │   ├── mean_reversion.py
│   │   └── base_strategy.py
│   ├── data/
│   │   ├── fetcher.py
│   │   └── preprocessor.py
│   ├── backtest/
│   │   ├── engine.py
│   │   └── metrics.py
│   └── api/
│       └── server.py
├── frontend/
│   ├── components/
│   │   └── Dashboard.tsx
│   └── pages/
│       └── index.tsx
├── config/
│   └── config.yaml
├── tests/
│   └── test_strategy.py
├── requirements.txt
├── Dockerfile
└── README.md"""


def generate_hypothetical_tree(query: str) -> str:
    """
    Use LLM to convert a user query into a hypothetical repo tree (HyDE).

    If LLM is not configured, times out, or fails, returns the raw query
    as fallback.

    This function is synchronous — call it via asyncio.to_thread().
    """
    client = _get_llm_client()
    if not client:
        print("  HyDE: LLM not configured, using raw query")
        return query

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            max_tokens=1024,
            temperature=0.3,
            timeout=LLM_TIMEOUT,
            messages=[
                {"role": "system", "content": HYDE_SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        )
        content = response.choices[0].message.content
        if not content or not content.strip():
            print("  HyDE: empty response, falling back to raw query")
            return query
        tree = content.strip()
        print(f"  HyDE tree generated ({len(tree)} chars) for: {query[:50]}")
        return tree
    except Exception as e:
        print(f"  HyDE failed ({type(e).__name__}: {e}), falling back to raw query")
        return query
