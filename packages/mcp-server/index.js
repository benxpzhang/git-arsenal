/**
 * Git Arsenal MCP Server
 *
 * Exposes two tools to AI agents:
 *   - search_repos: semantic search for GitHub repos
 *   - get_repo_detail: get detailed info for a specific repo
 *
 * Auto-registers an anonymous user if ARSENAL_TOKEN is not set.
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const API = process.env.ARSENAL_API_URL || "http://localhost:8003";
let TOKEN = process.env.ARSENAL_TOKEN || "";

// ── HTTP helpers ──
async function apiPost(path, body, timeoutMs = 90000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}),
      },
      body: JSON.stringify(body),
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function apiGet(path, timeoutMs = 30000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${API}${path}`, {
      headers: TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {},
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

// ── Auto-register anonymous user ──
async function ensureToken() {
  if (TOKEN) return;
  try {
    const data = await apiPost("/api/auth/anonymous", {});
    TOKEN = data.token;
    process.stderr.write(`[git-arsenal] Auto-registered anonymous user: ${data.user_id}\n`);
  } catch (e) {
    process.stderr.write(`[git-arsenal] Warning: auto-register failed: ${e.message}\n`);
  }
}

// ── MCP Server ──
const server = new McpServer({
  name: "git-arsenal",
  version: "1.0.0",
});

// Tool: search_repos
server.tool(
  "search_repos",
  "Search GitHub open-source repositories by natural language description. Returns matching repos with stars, language, description, and directory tree.",
  {
    query: z.string().describe("Natural language description of the project you're looking for"),
    keywords: z.array(z.string()).optional().describe(
      "3-5 real GitHub repo or org name fragments for keyword matching (lowercase, specific names). " +
      "e.g. query='RAG platform' → ['dify','langchain','ragflow','quivr','haystack']"
    ),
    repo_tree: z.string().optional().describe(
      "A hypothetical repo directory tree (20-35 lines, max-depth 4) using ├──/└──/│ connectors " +
      "with domain-specific filenames. Embedded and compared against real repo trees via vector similarity."
    ),
    repo_summary: z.string().optional().describe(
      "A 2-4 sentence project overview (~50-150 words) describing what the ideal repo does, " +
      "its core features, and tech stack — as if writing the first paragraph of its wiki page. " +
      "Embedded and compared against real repo wiki summaries via vector similarity."
    ),
    top_k: z.number().min(1).max(50).default(10).describe("Number of results to return"),
    language: z.string().optional().describe("Filter by programming language (e.g. 'Python', 'TypeScript')"),
    min_stars: z.number().optional().describe("Minimum star count filter"),
  },
  async ({ query, keywords, repo_tree, repo_summary, top_k, language, min_stars }) => {
    await ensureToken();
    try {
      const data = await apiPost("/api/search", {
        query,
        keywords: keywords || null,
        repo_tree: repo_tree || null,
        repo_summary: repo_summary || null,
        top_k: top_k || 10,
        language: language || null,
        min_stars: min_stars || null,
      });

      if (!data.results || data.results.length === 0) {
        return { content: [{ type: "text", text: "No repositories found matching your query." }] };
      }

      const cards = data.results.map((r) => ({
        full_name: r.full_name,
        stars: r.stars || 0,
        language: r.language || "",
        description: r.description || "",
        html_url: r.html_url || "",
      }));

      const llmText = data.results
        .map((r, i) => {
          const lines = [
            `${i + 1}. ${r.full_name} · ⭐${r.stars} · ${r.language || "N/A"}`,
          ];
          if (r.description) lines.push(`   ${r.description}`);
          if (r.tree_text) {
            const truncated = r.tree_text.split("\n").slice(0, 20).join("\n");
            lines.push(`   Tree:\n${truncated}`);
          }
          if (r.wiki_text) {
            lines.push(`   Wiki: ${r.wiki_text.slice(0, 150)}`);
          }
          return lines.join("\n");
        })
        .join("\n\n");

      const text = `<!--REPO_CARDS:${JSON.stringify(cards)}-->\n\n${llmText}`;
      return { content: [{ type: "text", text }] };
    } catch (e) {
      return {
        content: [{ type: "text", text: `Sorry, the search failed: ${e.message}. Please try again.` }],
        isError: true,
      };
    }
  }
);

// Tool: get_repo_detail
server.tool(
  "get_repo_detail",
  "Get detailed information about a specific GitHub repository. You can provide either full owner/name or just the project name for fuzzy matching.",
  {
    name: z.string().describe(
      "Repository name — either full 'owner/name' (e.g. 'facebook/react') or just the project name (e.g. 'react', 'langchain', 'openclaw')"
    ),
  },
  async ({ name }) => {
    await ensureToken();
    try {
      const isFullName = name.includes("/");
      const endpoint = isFullName
        ? `/api/repo/${name}`
        : `/api/repo-search/${encodeURIComponent(name)}`;
      const data = await apiGet(endpoint);

      const card = {
        full_name: data.full_name || name,
        stars: data.stars || 0,
        language: data.language || "",
        description: data.description || "",
        html_url: data.html_url || `https://github.com/${data.full_name || name}`,
      };

      const llmParts = [
        `${data.full_name || name} · ⭐${data.stars || 0} · ${data.language || "N/A"}`,
        data.description || "",
      ];
      if (data.tree_text) {
        llmParts.push(`Tree:\n${data.tree_text.split("\n").slice(0, 25).join("\n")}`);
      }
      if (data.wiki_text) {
        llmParts.push(`Wiki: ${data.wiki_text.slice(0, 300)}`);
      }

      const text = `<!--REPO_CARDS:${JSON.stringify([card])}-->\n\n${llmParts.join("\n")}`;
      return { content: [{ type: "text", text }] };
    } catch (e) {
      return {
        content: [{ type: "text", text: `Sorry, could not fetch repo details: ${e.message}` }],
        isError: true,
      };
    }
  }
);

// Start
async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("[git-arsenal] MCP server started\n");
}
main().catch((e) => {
  process.stderr.write(`[git-arsenal] Fatal: ${e.message}\n`);
  process.exit(1);
});
