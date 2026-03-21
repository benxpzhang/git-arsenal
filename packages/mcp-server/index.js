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
      "5-10 real GitHub repo or org name fragments for keyword matching (lowercase, specific names). " +
      "e.g. query='RAG platform' → ['dify','langchain','ragflow','llama-index','quivr','haystack']"
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

      const text = data.results
        .map((r, i) => {
          const parts = [
            `## ${i + 1}. ${r.full_name} ⭐ ${r.stars}`,
            r.description ? `> ${r.description}` : "",
            `- Language: ${r.language || "N/A"}`,
            `- URL: ${r.html_url}`,
            `- Match Score: ${(r.score * 100).toFixed(1)}%`,
          ];
          if (r.tree_text) {
            parts.push("", "```", r.tree_text, "```");
          }
          return parts.filter(Boolean).join("\n");
        })
        .join("\n\n---\n\n");

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
  "Get detailed information about a specific GitHub repository by owner/name.",
  {
    owner: z.string().describe("Repository owner (e.g. 'facebook')"),
    name: z.string().describe("Repository name (e.g. 'react')"),
  },
  async ({ owner, name }) => {
    await ensureToken();
    try {
      const data = await apiGet(`/api/repo/${owner}/${name}`);

      const parts = [
        `# ${data.full_name || `${owner}/${name}`}`,
        data.description ? `> ${data.description}` : "",
        "",
        `- Stars: ${data.stars || 0}`,
        `- Language: ${data.language || "N/A"}`,
        `- URL: ${data.html_url || `https://github.com/${owner}/${name}`}`,
      ];

      if (data.tree_text) {
        parts.push("", "## Directory Structure", "```", data.tree_text, "```");
      }

      return { content: [{ type: "text", text: parts.filter(Boolean).join("\n") }] };
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
