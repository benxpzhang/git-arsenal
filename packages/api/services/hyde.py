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


HYDE_SYSTEM_PROMPT = """你是一个资深 GitHub 开源项目架构师。用户会描述一个项目需求，你需要生成一个假想的、成熟的 GitHub 仓库目录结构（repo tree），max-depth=4。

要求：
1. 第一行格式："项目名 | N dirs | M files"
2. 使用 ├── 和 └── 连接符的标准 tree 格式
3. 生成 60-120 行，展示到 depth=4 的目录结构
4. 要像一个真实的、成熟的开源项目（不是玩具项目），包含：
   - .github/workflows/ CI/CD 配置
   - 核心源码目录（多层嵌套，每层有具体文件）
   - tests/ 测试目录
   - docs/ 文档目录
   - 配置文件（Dockerfile, Makefile, pyproject.toml 等）
5. 文件名要具体、专业，能体现项目功能和技术栈
6. 不要输出任何解释，只输出目录结构

示例（用户需求："web scraping API service"）：

firecrawl | 253 dirs | 1047 files
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   └── feature_request.md
│   └── workflows/
│       ├── deploy-image.yml
│       ├── publish-python-sdk.yml
│       ├── test-server.yml
│       └── npm-audit.yml
├── apps/
│   ├── api/
│   │   ├── src/
│   │   │   ├── controllers/
│   │   │   │   ├── v0/
│   │   │   │   │   ├── crawl.ts
│   │   │   │   │   ├── scrape.ts
│   │   │   │   │   └── search.ts
│   │   │   │   └── v1/
│   │   │   │       ├── crawl.ts
│   │   │   │       ├── extract.ts
│   │   │   │       └── map.ts
│   │   │   ├── services/
│   │   │   │   ├── billing/
│   │   │   │   │   ├── credit_billing.ts
│   │   │   │   │   └── issue_recharge.ts
│   │   │   │   ├── queue-worker.ts
│   │   │   │   ├── rate-limiter.ts
│   │   │   │   └── webhook.ts
│   │   │   ├── lib/
│   │   │   │   ├── scrape-events.ts
│   │   │   │   ├── extract/
│   │   │   │   │   ├── index.ts
│   │   │   │   │   └── completions.ts
│   │   │   │   └── LLM-extraction/
│   │   │   │       ├── models.ts
│   │   │   │       └── helpers.ts
│   │   │   └── index.ts
│   │   ├── package.json
│   │   └── tsconfig.json
│   ├── go-service/
│   │   ├── cmd/
│   │   │   └── server/
│   │   │       └── main.go
│   │   ├── internal/
│   │   │   ├── crawler/
│   │   │   │   ├── crawler.go
│   │   │   │   └── headless.go
│   │   │   ├── parser/
│   │   │   │   ├── html.go
│   │   │   │   ├── pdf.go
│   │   │   │   └── markdown.go
│   │   │   └── storage/
│   │   │       └── redis.go
│   │   └── go.mod
│   └── playwright-service/
│       ├── src/
│       │   ├── index.ts
│       │   └── browser_manager.ts
│       └── Dockerfile
├── sdks/
│   ├── python/
│   │   ├── firecrawl/
│   │   │   ├── __init__.py
│   │   │   └── firecrawl.py
│   │   └── pyproject.toml
│   └── js/
│       ├── src/
│       │   └── index.ts
│       └── package.json
├── docker-compose.yaml
├── Dockerfile
├── LICENSE
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
            max_tokens=2048,
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
