#!/usr/bin/env python3
"""
End-to-end search quality test.

Only provides a query — the full pipeline runs:
  1. LLM keyword extraction (fallback)
  2. LLM HyDE tree generation (fallback)
  3. Embedding (tree + wiki)
  4. Multi-recall + RRF

This mirrors what happens when a user hits POST /api/search with just a query string.

Usage:
    cd packages/api && python ../../scripts/test_e2e.py
"""
import sys
import time
import asyncio
from pathlib import Path

api_dir = str(Path(__file__).resolve().parent.parent / "packages" / "api")
if api_dir not in sys.path:
    sys.path.insert(0, api_dir)

from services.search import init_qdrant, multi_recall
from services.embedding import get_embedding, EmbeddingError
from services.query_parser import parse_query

TESTS = [
    # ── 50k ──
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
    # ── 10k ──
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
    # ── 5k ──
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
    # ── 1k ──
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
    # ── 500 ──
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


async def run_search(query: str):
    """Replicate the full route logic: single LLM → embed → recall → RRF."""
    t0 = time.time()

    # Phase 1: single LLM call → keywords + tree
    keywords, hypo_tree = await asyncio.to_thread(parse_query, query)
    t1 = time.time()
    print(f"    LLM: {t1-t0:.1f}s | kw={keywords}")

    # Phase 2: parallel embed tree + query
    async def embed_tree():
        try:
            return await asyncio.to_thread(get_embedding, hypo_tree)
        except EmbeddingError:
            try:
                return await asyncio.to_thread(get_embedding, query)
            except EmbeddingError:
                return None

    async def embed_query():
        try:
            return await asyncio.to_thread(get_embedding, query)
        except EmbeddingError:
            return None

    tree_vec, wiki_vec = await asyncio.gather(embed_tree(), embed_query())
    if tree_vec is None:
        return [], keywords, 0, time.time() - t0

    # Phase 3: recall + RRF
    candidates = await multi_recall(
        keywords=keywords,
        tree_vector=tree_vec,
        wiki_vector=wiki_vec,
        top_k_per_channel=50,
        rrf_top_k=20,
    )
    elapsed = time.time() - t0
    return candidates, keywords, len(candidates), elapsed


async def main():
    print("Initializing Qdrant...")
    init_qdrant()
    print(f"\nRunning {len(TESTS)} end-to-end tests (full pipeline, LLM fallback)\n")

    results = []
    for i, tc in enumerate(TESTS):
        query = tc["query"]
        expect = tc["expect"]

        print(f"\n{'─'*80}")
        print(f"[{i+1:2d}/{len(TESTS)}] {query}")

        candidates, keywords, n_results, elapsed = await run_search(query)

        result_names = {r["full_name"].lower() for r in candidates}
        hits = [e for e in expect if e.lower() in result_names]

        # Find ranks
        ranks = {}
        for e in expect:
            for j, r in enumerate(candidates):
                if r["full_name"].lower() == e.lower():
                    ranks[e] = j + 1
                    break

        n_hit = len(hits)
        n_exp = len(expect)
        status = "PASS" if n_hit == n_exp else ("PART" if n_hit > 0 else "MISS")

        print(f"  Keywords: {keywords}")
        print(f"  Time: {elapsed:.1f}s | Results: {n_results}")

        for j, r in enumerate(candidates[:10]):
            name = r["full_name"]
            stars = r["stars"]
            matched = name.lower() in {e.lower() for e in expect}
            marker = " <<<" if matched else ""
            print(f"    {j+1:2d}. {name:50s} {stars:>7,}★{marker}")

        rank_str = ", ".join(f"{e}@#{ranks.get(e, 'X')}" for e in expect)
        missed = [e for e in expect if e not in hits]
        print(f"  [{status}] {rank_str}")
        if missed:
            print(f"  Missed: {missed}")

        results.append({
            "query": query,
            "hits": n_hit,
            "total": n_exp,
            "elapsed": elapsed,
            "status": status,
        })

    # Summary
    print(f"\n{'═'*80}")
    print("SUMMARY")
    print(f"{'═'*80}")

    total_hits = sum(r["hits"] for r in results)
    total_exp = sum(r["total"] for r in results)
    full_pass = sum(1 for r in results if r["status"] == "PASS")
    partial = sum(1 for r in results if r["status"] == "PART")
    miss = sum(1 for r in results if r["status"] == "MISS")
    avg_time = sum(r["elapsed"] for r in results) / len(results)

    print(f"  Total: {len(results)} queries")
    print(f"  PASS: {full_pass} | PART: {partial} | MISS: {miss}")
    print(f"  Hits: {total_hits}/{total_exp} ({total_hits/total_exp*100:.0f}%)")
    print(f"  Avg latency: {avg_time:.1f}s")

    # Band summary (10 per band)
    bands = ["50k", "10k", "5k", "1k", "500"]
    for idx, band in enumerate(bands):
        band_r = results[idx*10:(idx+1)*10]
        bh = sum(r["hits"] for r in band_r)
        be = sum(r["total"] for r in band_r)
        bp = sum(1 for r in band_r if r["status"] == "PASS")
        bt = sum(r["elapsed"] for r in band_r) / len(band_r)
        print(f"  {band:>3s}: {bp}/10 PASS | {bh}/{be} hits | avg {bt:.1f}s")

    # List failures
    failures = [r for r in results if r["status"] != "PASS"]
    if failures:
        print(f"\nFailed queries:")
        for r in failures:
            print(f"  [{r['status']}] {r['query'][:60]}")


if __name__ == "__main__":
    asyncio.run(main())
