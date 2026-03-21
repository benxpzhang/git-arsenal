#!/usr/bin/env python3
"""
3-channel e2e search benchmark: keyword + tree + wiki.
Uses glm-4.7, concurrent LLM + embed calls with semaphore control.
"""
import sys, time, asyncio, json, re, os, random
from pathlib import Path
from openai import OpenAI

api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from services.search import init_qdrant, recall_by_name, recall_by_tree, recall_by_wiki, rrf_merge
from services.embedding import get_embedding

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
LLM_MODEL = "glm-4.7"

llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL, timeout=120)
llm_sem = asyncio.Semaphore(1)  # glm-4.7: strict 1 concurrency
embed_sem = asyncio.Semaphore(5)

PARSE_PROMPT = """You are a GitHub open-source expert. Given a user query, output a JSON with:
1. "keywords": 5-10 real GitHub repo or org name fragments (lowercase, specific names not generic words).
2. "tree": A hypothetical repo directory tree (max-depth 4, 60-120 lines) using ├──/└──/│ connectors.

Output ONLY JSON. Example:
{"keywords":["firecrawl","scrapy","crawlee"],"tree":"web-scraper | 60 dirs\\n├── apps/\\n│   └── api/\\n│       └── src/\\n└── README.md"}"""


async def llm_parse(query: str, max_retries: int = 3) -> tuple[list[str], str]:
    for attempt in range(max_retries):
        async with llm_sem:
            try:
                resp = await asyncio.to_thread(
                    lambda: llm_client.chat.completions.create(
                        model=LLM_MODEL, max_tokens=4096, temperature=0.3, timeout=120,
                        messages=[
                            {"role": "system", "content": PARSE_PROMPT},
                            {"role": "user", "content": query},
                        ],
                    )
                )
                text = (resp.choices[0].message.content or "").strip()
                text = re.sub(r'```(?:json)?\s*', '', text).rstrip('`').strip()
                match = re.search(r'\{.*\}', text, re.DOTALL)
                if match:
                    obj = json.loads(match.group())
                else:
                    obj = json.loads(text)
                kw = [str(k).lower().strip() for k in obj.get("keywords", []) if k]
                tree = obj.get("tree", query) or query
                return kw, tree
            except Exception as e:
                err_name = type(e).__name__
                if "RateLimit" in err_name and attempt < max_retries - 1:
                    wait = 3 * (attempt + 1)
                    await asyncio.sleep(wait)
                    continue
                if attempt == max_retries - 1:
                    print(f"  LLM fail [{query[:30]}]: {err_name}")
                    return [], query
    return [], query


async def embed(text: str) -> list[float] | None:
    async with embed_sem:
        try:
            return await asyncio.to_thread(get_embedding, text)
        except Exception:
            return None


# ── Trajectory recording ──────────────────────────────────────────

SEARCH_MODE_SYSTEM_PROMPT = (
    "You are **Git Arsenal Search Assistant** — an AI that helps users discover "
    "the best open-source GitHub repositories from a curated index of 150 000+ projects.\n\n"
    "## How Search Works\n\n"
    "Our search engine matches repositories by comparing directory tree structures via "
    "vector similarity (not keywords).\n"
    "When calling search_repos you MUST provide a **hypothetical_tree** — imagine what the "
    "ideal repo's file structure would look like. This tree is embedded and compared against "
    "150 000+ real repo trees stored in Qdrant.\n\n"
    "A good hypothetical tree is 20-35 lines, uses realistic filenames that capture the domain.\n\n"
    "### Example\n\n"
    "For \"Rust web frameworks\", you would generate:\n\n"
    "rust-web-framework | 20 dirs | 55 files\n"
    "├── src/\n│   ├── routing/\n│   │   ├── mod.rs\n│   │   ├── router.rs\n│   │   └── handler.rs\n"
    "│   ├── middleware/\n│   │   ├── auth.rs\n│   │   ├── cors.rs\n│   │   └── logger.rs\n"
    "│   ├── extractors/\n│   │   ├── json.rs\n│   │   └── query.rs\n"
    "│   ├── response/\n│   │   └── mod.rs\n│   ├── server.rs\n│   └── lib.rs\n"
    "├── examples/\n│   ├── hello_world.rs\n│   └── rest_api.rs\n"
    "├── tests/\n│   └── integration_test.rs\n├── Cargo.toml\n├── LICENSE\n└── README.md\n\n"
    "## Strategy\n\n"
    "1. **Understand first** — if the user's query is vague, ask one clarifying question before searching.\n"
    "2. **Exactly ONE search** — call search_repos ONCE with a well-crafted hypothetical_tree "
    "and top_k 15. NEVER search more than once per user message.\n"
    "3. **Skip get_repo_detail** unless the user explicitly asks to dive into a specific repository.\n"
    "4. **Always present results** — after receiving search results, IMMEDIATELY present them. "
    "Do NOT say \"let me search again\". Work with what you have.\n\n"
    "## Response Format\n\n"
    "After receiving tool results, present the top 5-10 as a ranked table:\n\n"
    "| # | Repository | Stars | Language | Why it matches |\n"
    "|---|-----------|-------|----------|----------------|\n"
    "| 1 | [owner/repo](url) | ⭐ 45.2k | Python | One-sentence reason |\n\n"
    "End with a short recommendation (1-2 sentences) and, if relevant, a follow-up question.\n\n"
    "## Critical Rules\n\n"
    "- **ONE search only** — never call search_repos more than once.\n"
    "- Always **search before answering** — never guess from memory.\n"
    "- Be **concise** — users want quick answers, not essays.\n"
    "- If results don't match perfectly, present the best matches and suggest refining.\n"
    "- For follow-up questions, leverage prior search context instead of re-searching.\n"
    "- Casual conversation (greetings, thanks, off-topic) — reply naturally, no tools.\n"
    "- After receiving tool results, you MUST generate a text response with the table."
)

SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_repos",
            "description": (
                "Search GitHub open-source repositories by natural language description. "
                "Returns matching repos with stars, language, description, and directory tree."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language description of the project you're looking for",
                    },
                    "keywords": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "5-10 real GitHub repo or org name fragments for keyword matching "
                            "(lowercase, specific names). e.g. ['dify','langchain','ragflow']"
                        ),
                    },
                    "hypothetical_tree": {
                        "type": "string",
                        "description": (
                            "A hypothetical repo directory tree (20-35 lines, max-depth 4) "
                            "using tree connectors with domain-specific filenames. "
                            "Embedded and compared against real repo trees via vector similarity."
                        ),
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results to return (1-50, default 10)",
                    },
                    "language": {
                        "type": "string",
                        "description": "Filter by programming language (e.g. 'Python', 'TypeScript')",
                    },
                    "min_stars": {
                        "type": "integer",
                        "description": "Minimum star count filter",
                    },
                },
                "required": ["query"],
            },
        },
    }
]


def _format_tool_result(results: list[dict]) -> str:
    """Format search results the same way the MCP server does."""
    parts = []
    for i, r in enumerate(results):
        lines = [f"## {i + 1}. {r['full_name']} ⭐ {r['stars']}"]
        if r.get("description"):
            lines.append(f"> {r['description']}")
        lines.append(f"- Language: {r.get('language') or 'N/A'}")
        lines.append(f"- URL: {r.get('html_url', '')}")
        score = r.get("rrf_score", r.get("score", 0))
        lines.append(f"- Match Score: {score * 100:.1f}%")
        if r.get("tree_text"):
            lines.extend(["", "```", r["tree_text"], "```"])
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


def _msg_to_serializable(msg) -> dict:
    """Convert an OpenAI message object to a plain dict for JSON."""
    d: dict = {"role": msg.role}
    if msg.content:
        d["content"] = msg.content
    if getattr(msg, "tool_calls", None):
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in msg.tool_calls
        ]
    return d


async def _llm_call_with_retry(messages, tools=None, max_retries=4):
    """LLM call with exponential backoff on rate limit."""
    for attempt in range(max_retries):
        try:
            async with llm_sem:
                kwargs = dict(model=LLM_MODEL, max_tokens=4096, temperature=0.3,
                              timeout=120, messages=messages)
                if tools:
                    kwargs["tools"] = tools
                return await asyncio.to_thread(
                    lambda: llm_client.chat.completions.create(**kwargs)
                )
        except Exception as e:
            if "RateLimit" in type(e).__name__ or "429" in str(e):
                wait = 5 * (attempt + 1)
                print(f"    Rate limited, retry in {wait}s...")
                await asyncio.sleep(wait)
                continue
            raise
    return None


async def record_trajectory(tc: dict, merged_results: list[dict]) -> dict | None:
    """Full tool-calling flow: system→user→tool_call→tool_result→assistant."""
    query = tc["query"]
    messages = [
        {"role": "system", "content": SEARCH_MODE_SYSTEM_PROMPT},
        {"role": "user", "content": query},
    ]

    try:
        resp1 = await _llm_call_with_retry(messages, tools=SEARCH_TOOLS)
        if resp1 is None:
            print(f"    Trajectory step-1: exhausted retries")
            return None
    except Exception as e:
        print(f"    Trajectory step-1 failed: {type(e).__name__}: {e}")
        return None

    msg1 = resp1.choices[0].message

    if not getattr(msg1, "tool_calls", None):
        messages.append({"role": "assistant", "content": msg1.content or ""})
        return {"query": query, "expect": tc["expect"], "messages": messages}

    tool_call = msg1.tool_calls[0]
    messages.append(_msg_to_serializable(msg1))

    tool_result_text = _format_tool_result(merged_results[:10])
    messages.append({
        "role": "tool",
        "tool_call_id": tool_call.id,
        "content": tool_result_text,
    })

    await asyncio.sleep(3)

    try:
        resp2 = await _llm_call_with_retry(messages)
        if resp2 is None:
            print(f"    Trajectory step-2: exhausted retries")
            messages.append({"role": "assistant", "content": "[generation failed: rate limit]"})
            return {"query": query, "expect": tc["expect"], "messages": messages}
    except Exception as e:
        print(f"    Trajectory step-2 failed: {type(e).__name__}: {e}")
        messages.append({"role": "assistant", "content": f"[generation failed: {e}]"})
        return {"query": query, "expect": tc["expect"], "messages": messages}

    messages.append({"role": "assistant", "content": resp2.choices[0].message.content or ""})
    return {"query": query, "expect": tc["expect"], "messages": messages}


TESTS = [
    {"query": "有个在线画图白板，画出来像手绘风格的，好多人用来画架构图", "expect": ["excalidraw/excalidraw"]},
    {"query": "开源的远程桌面，可以自建服务器那种，不想用TeamViewer", "expect": ["rustdesk/rustdesk"]},
    {"query": "node-based workflow editor for stable diffusion, drag and drop nodes", "expect": ["Comfy-Org/ComfyUI"]},
    {"query": "OpenAI那个语音转文字的模型，可以本地跑的", "expect": ["openai/whisper"]},
    {"query": "self-hosted Google Photos alternative with mobile app and face recognition", "expect": ["immich-app/immich"]},
    {"query": "那个用Rust写的超快JS运行时，还自带打包和包管理器", "expect": ["oven-sh/bun"]},
    {"query": "微软出的一个工具，可以把PDF、Word、PPT这些转成Markdown", "expect": ["microsoft/markitdown"]},
    {"query": "好看的网站监控面板，可以自己部署，支持多种协议监控", "expect": ["louislam/uptime-kuma"]},
    {"query": "drop a screenshot and it generates HTML/React code", "expect": ["abi/screenshot-to-code"]},
    {"query": "RAG知识库平台，支持向量搜索和工作流编排", "expect": ["langgenius/dify", "infiniflow/ragflow"]},
    {"query": "pydantic团队出的AI agent框架，类型安全", "expect": ["pydantic/pydantic-ai"]},
    {"query": "之前看到一个Python内存分析工具，彭博社开源的，能生成火焰图", "expect": ["bloomberg/memray"]},
    {"query": "JS library to generate realistic fake data for testing", "expect": ["faker-js/faker"]},
    {"query": "能在浏览器里直接跑PostgreSQL的WASM项目", "expect": ["electric-sql/pglite"]},
    {"query": "Karpathy写的教学用的小型autograd引擎", "expect": ["karpathy/micrograd"]},
    {"query": "最近新出的开源视频生成大模型，万视频", "expect": ["Wan-Video/Wan2.1"]},
    {"query": "a text-to-speech system that can clone voices, sounds very realistic", "expect": ["neonbjb/tortoise-tts"]},
    {"query": "比df命令好看的磁盘占用查看工具", "expect": ["muesli/duf"]},
    {"query": "开源的Auth0替代方案，可以自部署", "expect": ["supertokens/supertokens-core"]},
    {"query": "开源的Codespaces替代品，支持Docker和K8s后端", "expect": ["loft-sh/devpod"]},
    {"query": "桌面端Kubernetes管理工具，Electron做的", "expect": ["rancher-sandbox/rancher-desktop"]},
    {"query": "从两张照片恢复3D场景的深度学习方法", "expect": ["naver/dust3r"]},
    {"query": "Neovim的调试插件，支持DAP协议", "expect": ["mfussenegger/nvim-dap"]},
    {"query": "用Rust从头写的Minecraft服务端", "expect": ["Pumpkin-MC/Pumpkin"]},
    {"query": "text-to-3D generation using NeRF and score distillation", "expect": ["threestudio-project/threestudio"]},
    {"query": "教你数据可视化该做什么不该做什么的repo", "expect": ["cxli233/FriendsDontLetFriends"]},
    {"query": "用LLM自动把代码从一个语言迁移到另一个", "expect": ["joshpxyne/gpt-migrate"]},
    {"query": "比AUTOMATIC1111功能更全的Stable Diffusion WebUI", "expect": ["vladmandic/sdnext"]},
    {"query": "安卓上看漫画和番剧的app，支持各种源", "expect": ["aniyomiorg/aniyomi"]},
    {"query": "金融数据库，包含股票ETF基金数据", "expect": ["JerBouma/FinanceDatabase"]},
    {"query": "安全测试工具，专门绕过网站403限制的", "expect": ["devploit/nomore403"]},
    {"query": "git操作搞砸了怎么撤销？有没有undo工具", "expect": ["Bhupesh-V/ugit"]},
    {"query": "neovim breadcrumbs plugin like VS Code", "expect": ["Bekaboo/dropbar.nvim"]},
    {"query": "CLI tool that uses AI to write git commit messages", "expect": ["appleboy/CodeGPT"]},
    {"query": "SolidJS的reactive primitives工具库", "expect": ["solidjs-community/solid-primitives"]},
    {"query": "ESP32做的RF安全工具，扫描蓝牙WiFi", "expect": ["cifertech/nRFBox"]},
    {"query": "让AI控制Windows桌面的agent", "expect": ["CursorTouch/Windows-Use"]},
    {"query": "类似Vercel的ComfyUI工作流部署平台", "expect": ["BennyKok/comfyui-deploy"]},
    {"query": "把Next.js部署到Cloudflare Pages的CLI工具", "expect": ["cloudflare/next-on-pages"]},
    {"query": "开源headless CMS加实时数据库", "expect": ["ontola/atomic-server"]},
    {"query": "Next.js集成Plausible Analytics的库", "expect": ["4lejandrito/next-plausible"]},
    {"query": "C++断言库，失败时打印超详细的诊断信息", "expect": ["jeremy-rifkin/libassert"]},
    {"query": "Cockpit的文件管理器插件", "expect": ["45Drives/cockpit-navigator"]},
    {"query": "console.log自动加文件名行号的插件", "expect": ["unplugin/unplugin-turbo-console"]},
    {"query": "single HTML file LLM chat frontend", "expect": ["lmg-anon/mikupad"]},
    {"query": "shadcn/ui的SolidJS移植版", "expect": ["hngngn/shadcn-solid"]},
    {"query": "PostgreSQL负载压测，模拟死锁和长事务", "expect": ["lesovsky/noisia"]},
    {"query": "OpenAPI schema generator for Hono router", "expect": ["cloudflare/chanfana"]},
    {"query": "让git commit hash变成递增序号的工具", "expect": ["zegl/extremely-linear"]},
    {"query": "Python写的无限画板，可以加AI插件", "expect": ["carefree0910/carefree-drawboard"]},
]


async def run_one(tc: dict) -> dict:
    q = tc["query"]
    expects = tc["expect"]
    t0 = time.time()

    keywords, hypo_tree = await llm_parse(q)

    tree_vec_task = embed(hypo_tree)
    wiki_vec_task = embed(q)
    tree_vec, wiki_vec = await asyncio.gather(tree_vec_task, wiki_vec_task)

    if tree_vec is None:
        tree_vec = wiki_vec
    if tree_vec is None:
        return {
            "query": q, "expects": expects, "keywords": keywords,
            "kw_hits": [], "tree_hits": [], "wiki_hits": [], "top10": [],
            "merged_full": [], "elapsed": time.time() - t0,
        }

    tasks = [
        recall_by_name(keywords, limit=50),
        recall_by_tree(tree_vec, limit=50),
    ]
    if wiki_vec is not None:
        tasks.append(recall_by_wiki(wiki_vec, limit=50))

    recall_results = await asyncio.gather(*tasks, return_exceptions=True)
    name_results = recall_results[0] if not isinstance(recall_results[0], Exception) else []
    tree_results = recall_results[1] if not isinstance(recall_results[1], Exception) else []
    wiki_results = recall_results[2] if len(recall_results) > 2 and not isinstance(recall_results[2], Exception) else []

    name_set = {r["full_name"].lower() for r in name_results}
    tree_set = {r["full_name"].lower() for r in tree_results}
    wiki_set = {r["full_name"].lower() for r in wiki_results}

    all_lists = [name_results, tree_results]
    if wiki_results:
        all_lists.append(wiki_results)
    merged = rrf_merge(all_lists, top_k=10)
    top10 = [{"full_name": r["full_name"], "stars": r["stars"]} for r in merged]

    kw_hits = [e for e in expects if e.lower() in name_set]
    tree_hits = [e for e in expects if e.lower() in tree_set]
    wiki_hits = [e for e in expects if e.lower() in wiki_set]

    elapsed = time.time() - t0
    return {
        "query": q, "expects": expects, "keywords": keywords,
        "kw_hits": kw_hits, "tree_hits": tree_hits, "wiki_hits": wiki_hits,
        "top10": top10, "merged_full": merged, "elapsed": elapsed,
    }


async def main():
    traj_file = Path(__file__).resolve().parent / "e2e_trajectories_glm47.jsonl"
    if traj_file.exists():
        traj_file.unlink()

    print("Initializing Qdrant...")
    init_qdrant()

    sample_size = 10
    sampled = sorted(random.sample(range(len(TESTS)), sample_size))
    sampled_tests = [TESTS[i] for i in sampled]
    print(f"\nSampled {sample_size} tests (indices {sampled}), model={LLM_MODEL}\n")

    t0 = time.time()
    results = []
    n = len(sampled_tests)

    for i, tc in enumerate(sampled_tests):
        # ── Phase 1: search benchmark ──
        r = await run_one(tc)
        results.append(r)
        expects = tc["expect"]
        union_hits = {e for e in expects if (e in r["kw_hits"] or e in r["tree_hits"] or e in r["wiki_hits"])}
        status = "PASS" if len(union_hits) == len(expects) else ("PART" if union_hits else "MISS")

        kh = len(r["kw_hits"]); th = len(r["tree_hits"]); wh = len(r["wiki_hits"])
        print(f"\n  [{i+1:2d}/{n}] [{status}] kw={kh} tree={th} wiki={wh} / {len(expects)} | {tc['query'][:45]}")
        print(f"    keywords: {r['keywords'][:8]}")
        for idx, item in enumerate(r["top10"], 1):
            print(f"    {idx:2d}. {item['full_name']:50s} {item['stars']:>7,}★")

        # ── Phase 2: record trajectory ──
        await asyncio.sleep(5)
        merged = r.get("merged_full", [])
        print(f"    Recording trajectory...")
        traj = await record_trajectory(tc, merged)
        if traj:
            with traj_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(traj, ensure_ascii=False) + "\n")
            n_msgs = len(traj["messages"])
            has_tool = any(m.get("tool_calls") for m in traj["messages"])
            print(f"    Trajectory OK: {n_msgs} messages, tool_call={'yes' if has_tool else 'no'}")
        else:
            print(f"    Trajectory SKIP (LLM failed)")

        await asyncio.sleep(5)

    wall_time = time.time() - t0

    traj_count = sum(1 for _ in traj_file.open() if _.strip()) if traj_file.exists() else 0
    print(f"\n{'='*70}")
    print(f"Model: {LLM_MODEL} | Wall time: {wall_time:.0f}s | Queries: {n}")
    print(f"{'='*70}")

    total_exp = sum(len(r["expects"]) for r in results)
    any_hit = sum(1 for r in results for e in r["expects"]
                  if e in r["kw_hits"] or e in r["tree_hits"] or e in r["wiki_hits"])
    print(f"  Any hit (recall): {any_hit}/{total_exp} ({any_hit/total_exp*100:.0f}%)")
    print(f"  Trajectories:     {traj_count}/{n} saved → {traj_file}")


if __name__ == "__main__":
    asyncio.run(main())
