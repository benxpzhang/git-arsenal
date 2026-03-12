#!/usr/bin/env python3
"""
Qdrant 搜索测试脚本 — 交互式 & 批量测试

用法:
    python scripts/test_qdrant.py                  # 交互式：输入描述，看推荐结果
    python scripts/test_qdrant.py --batch           # 跑预设的批量测试用例
    python scripts/test_qdrant.py --query "xxx"     # 单次查询

环境变量 (读 .env):
    OPENAI_API_KEY       DashScope API Key
    OPENAI_BASE_URL      DashScope Endpoint
    EMBEDDING_MODEL      text-embedding-v4
    QDRANT_URL           http://localhost:6333
"""

import os
import sys
import time
import argparse
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from openai import OpenAI
from qdrant_client import QdrantClient, models

# ── Config ──
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
COLLECTION = "repos"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-4-flash")  # 免费模型生成 tree
EMBED_API_KEY = os.getenv("OPENAI_API_KEY", "")
EMBED_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
EMBED_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")


def get_clients():
    embed_client = OpenAI(api_key=EMBED_API_KEY, base_url=EMBED_BASE_URL)
    llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    qdrant = QdrantClient(url=QDRANT_URL, timeout=30)
    return embed_client, llm_client, qdrant


def generate_hypothetical_tree(llm_client, query: str) -> str:
    """用 LLM 把用户 query 转成假想的 repo tree (HyDE)"""
    prompt = f"""Based on the user's description, generate a hypothetical GitHub repository directory tree.
The tree should be 20-40 lines, realistic, with domain-specific file/folder names.
Format: first line "project-name | N dirs | M files", then tree lines with ├──/└──/│.

User query: {query}

Generate the tree directly, no explanation:"""

    t0 = time.time()
    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=800,
    )
    tree = resp.choices[0].message.content.strip()
    elapsed = time.time() - t0
    return tree, elapsed


def embed_text(embed_client, text: str):
    """生成 embedding"""
    t0 = time.time()
    resp = embed_client.embeddings.create(
        model=EMBED_MODEL,
        input=text,
        dimensions=1024,
        encoding_format="float",
    )
    vec = resp.data[0].embedding
    elapsed = time.time() - t0
    return vec, elapsed


def search_qdrant(qdrant, vec, top_k=10, language=None, min_stars=None):
    """在 Qdrant 中搜索"""
    # 构建过滤条件
    must_conditions = []
    if language:
        must_conditions.append(
            models.FieldCondition(key="language", match=models.MatchValue(value=language))
        )
    if min_stars and min_stars > 0:
        must_conditions.append(
            models.FieldCondition(key="stars", range=models.Range(gte=min_stars))
        )

    search_filter = models.Filter(must=must_conditions) if must_conditions else None

    t0 = time.time()
    results = qdrant.query_points(
        collection_name=COLLECTION,
        query=vec,
        using="tree",
        limit=top_k,
        query_filter=search_filter,
        with_payload=True,
    )
    elapsed = time.time() - t0
    return results.points, elapsed


def format_stars(n):
    if n >= 1000:
        return f"{n/1000:.1f}k"
    return str(n)


def print_results(points, show_tree=False):
    """打印搜索结果"""
    for i, pt in enumerate(points):
        p = pt.payload
        desc = (p.get("description", "") or "")[:100]
        line = f"  {i+1:>2}. {p['full_name']:<40} ⭐{format_stars(p['stars']):>6}  {p['language'] or '?':<15} score={pt.score:.4f}"
        print(line)
        if desc:
            print(f"      {desc}")
        if show_tree:
            tree = (p.get("tree_text", "") or "")[:300]
            if tree:
                print(f"      📁 {tree[:200]}...")
        print()


def full_search(embed_client, llm_client, qdrant, query, top_k=10, language=None, min_stars=None, show_tree=False):
    """完整搜索流程：HyDE → Embed → Search"""
    print(f"\n{'='*70}")
    print(f"🔍 Query: {query}")
    if language:
        print(f"   Filter: language={language}")
    if min_stars:
        print(f"   Filter: stars≥{min_stars}")
    print(f"{'='*70}")

    # Step 1: HyDE
    print("\n⏳ Step 1: 生成假想项目结构 (HyDE) ...")
    tree, t_hyde = generate_hypothetical_tree(llm_client, query)
    print(f"   ({t_hyde:.2f}s)")
    # 只显示前 5 行
    lines = tree.split("\n")
    for l in lines[:5]:
        print(f"   {l}")
    if len(lines) > 5:
        print(f"   ... ({len(lines)} lines total)")

    # Step 2: Embed
    print(f"\n⏳ Step 2: 生成 embedding ...")
    vec, t_embed = embed_text(embed_client, tree)
    print(f"   ({t_embed:.2f}s, 1024-dim)")

    # Step 3: Search
    print(f"\n⏳ Step 3: Qdrant 向量搜索 ...")
    points, t_search = search_qdrant(qdrant, vec, top_k, language, min_stars)
    print(f"   ({t_search*1000:.0f}ms, {len(points)} results)")

    # Results
    print(f"\n📊 Results:")
    print_results(points, show_tree=show_tree)

    # Timing
    total = t_hyde + t_embed + t_search
    print(f"⏱  Total: {total:.2f}s  (HyDE={t_hyde:.2f}s + Embed={t_embed:.2f}s + Search={t_search*1000:.0f}ms)")
    return points


# ── 预设测试用例 ──
BATCH_CASES = [
    {"query": "用 Python 做 A 股量化回测的框架"},
    {"query": "RAG knowledge base with PDF ingestion and hybrid search"},
    {"query": "AI coding agent that can edit files and run commands"},
    {"query": "开源 Notion 替代品，支持协作编辑和数据库视图"},
    {"query": "Rust web framework like Express.js", "language": "Rust"},
    {"query": "React component library with dark mode", "language": "TypeScript"},
    {"query": "MCP server for connecting LLM to databases"},
    {"query": "3D visualization of graph data using WebGL"},
    {"query": "微信小程序商城模板", "language": "JavaScript"},
    {"query": "distributed training framework for LLM", "min_stars": 500},
]


def run_batch(embed_client, llm_client, qdrant):
    """批量测试"""
    print(f"\n🧪 Running {len(BATCH_CASES)} batch tests...\n")
    for case in BATCH_CASES:
        full_search(
            embed_client, llm_client, qdrant,
            query=case["query"],
            top_k=5,
            language=case.get("language"),
            min_stars=case.get("min_stars"),
        )


def run_interactive(embed_client, llm_client, qdrant):
    """交互式搜索"""
    print("\n🚀 Qdrant 搜索测试 (交互模式)")
    print("   输入搜索描述，按 Enter 搜索")
    print("   支持命令:")
    print("     /lang Python      — 按语言过滤")
    print("     /stars 1000       — 按最低星数过滤")
    print("     /top 20           — 设置返回数量")
    print("     /tree             — 显示/隐藏项目结构")
    print("     /reset            — 重置过滤条件")
    print("     /quit             — 退出")
    print()

    language = None
    min_stars = None
    top_k = 10
    show_tree = False

    while True:
        try:
            query = input("🔍 > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n👋 Bye!")
            break

        if not query:
            continue

        if query.startswith("/"):
            parts = query.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd == "/quit" or cmd == "/exit" or cmd == "/q":
                print("👋 Bye!")
                break
            elif cmd == "/lang":
                language = arg if arg else None
                print(f"   ✅ language filter: {language or 'none'}")
            elif cmd == "/stars":
                try:
                    min_stars = int(arg) if arg else None
                except ValueError:
                    min_stars = None
                print(f"   ✅ min_stars filter: {min_stars or 'none'}")
            elif cmd == "/top":
                try:
                    top_k = int(arg) if arg else 10
                except ValueError:
                    top_k = 10
                print(f"   ✅ top_k: {top_k}")
            elif cmd == "/tree":
                show_tree = not show_tree
                print(f"   ✅ show tree: {show_tree}")
            elif cmd == "/reset":
                language = None
                min_stars = None
                top_k = 10
                show_tree = False
                print("   ✅ filters reset")
            else:
                print(f"   ❓ Unknown command: {cmd}")
            continue

        full_search(embed_client, llm_client, qdrant, query, top_k, language, min_stars, show_tree)


def main():
    parser = argparse.ArgumentParser(description="Test Qdrant search")
    parser.add_argument("--batch", action="store_true", help="Run batch test cases")
    parser.add_argument("--query", "-q", type=str, help="Single query")
    parser.add_argument("--language", "-l", type=str, help="Filter by language")
    parser.add_argument("--stars", "-s", type=int, help="Minimum stars")
    parser.add_argument("--top", "-k", type=int, default=10, help="Top K results")
    parser.add_argument("--tree", action="store_true", help="Show repo tree in results")
    args = parser.parse_args()

    embed_client, llm_client, qdrant = get_clients()

    # Verify connection
    try:
        info = qdrant.get_collection(COLLECTION)
        print(f"✅ Qdrant: {info.points_count:,} points in '{COLLECTION}'")
    except Exception as e:
        print(f"❌ Cannot connect to Qdrant: {e}")
        sys.exit(1)

    if args.batch:
        run_batch(embed_client, llm_client, qdrant)
    elif args.query:
        full_search(embed_client, llm_client, qdrant, args.query, args.top, args.language, args.stars, args.tree)
    else:
        run_interactive(embed_client, llm_client, qdrant)


if __name__ == "__main__":
    main()
