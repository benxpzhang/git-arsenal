/**
 * API client for Git Arsenal backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || "";

async function handleRes(res: Response) {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== "undefined" ? localStorage.getItem("arsenal_token") : null;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/* ── Auth ── */
export async function registerAnonymous() {
  const res = await fetch(`${BASE}/api/auth/anonymous`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  return handleRes(res);
}

export async function getMe() {
  const res = await fetch(`${BASE}/api/auth/me`, { headers: authHeaders() });
  return handleRes(res);
}

/* ── Search ── */
export interface SearchResult {
  id: number;
  score: number;
  full_name: string;
  stars: number;
  language: string;
  description: string;
  html_url: string;
  tree_text: string;
}

export interface SearchResponse {
  query: string;
  hypothetical_tree: string;
  results: SearchResult[];
}

export async function searchRepos(query: string, topK = 15): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ query, top_k: topK }),
  });
  return handleRes(res);
}

/* ── Galaxy ── */
export interface GalaxyNode {
  id: number;
  name: string;
  stars: number;
  val: number;
  color: string;
  rawLang: string;
  cluster: string;
  leafId: number;
  url: string;
  role: string;
  x?: number;
  y?: number;
  z?: number;
  edgeCount?: number;
}

export interface GalaxyLink {
  source: number;
  target: number;
  sim: number;
}

export interface GalaxySubgraph {
  focus: number;
  focusName: string;
  clusterName: string;
  clusterSize: number;
  leafId?: number;
  parentClusterId?: number | null;
  nodes: GalaxyNode[];
  links: GalaxyLink[];
  totalRepos: number;
}

export async function getGalaxySubgraph(params: Record<string, string | number | boolean>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) qs.set(k, String(v));
  }
  const res = await fetch(`${BASE}/api/galaxy/subgraph?${qs}`, { headers: authHeaders() });
  return handleRes(res);
}

export async function getGalaxyCluster(clusterId: number, focusId?: number, maxNodes = 500) {
  const qs = new URLSearchParams();
  qs.set("cluster_id", String(clusterId));
  qs.set("max_nodes", String(maxNodes));
  if (focusId !== undefined) qs.set("focus_id", String(focusId));
  const res = await fetch(`${BASE}/api/galaxy/cluster?${qs}`, { headers: authHeaders() });
  return handleRes(res);
}

export async function searchGalaxy(q: string, limit = 12) {
  const res = await fetch(`${BASE}/api/galaxy/search?q=${encodeURIComponent(q)}&limit=${limit}`, {
    headers: authHeaders(),
  });
  return handleRes(res);
}

export async function getGalaxyNeighbors(id: number, limit = 15): Promise<{ nodes: GalaxyNode[]; links: GalaxyLink[] }> {
  const res = await fetch(`${BASE}/api/galaxy/neighbors?id=${id}&limit=${limit}`, { headers: authHeaders() });
  return handleRes(res);
}

export async function getGalaxyDetail(id: number) {
  const res = await fetch(`${BASE}/api/galaxy/detail?id=${id}`, { headers: authHeaders() });
  return handleRes(res);
}

/* ── Conversations ── */
export async function createConversation(title?: string) {
  const res = await fetch(`${BASE}/api/conversations`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title }),
  });
  return handleRes(res);
}

export async function listConversations() {
  const res = await fetch(`${BASE}/api/conversations`, { headers: authHeaders() });
  return handleRes(res);
}

export async function getConversation(id: string) {
  const res = await fetch(`${BASE}/api/conversations/${id}`, { headers: authHeaders() });
  return handleRes(res);
}

export async function addMessage(convId: string, role: string, content: string) {
  const res = await fetch(`${BASE}/api/conversations/${convId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ role, content }),
  });
  return handleRes(res);
}

export async function deleteConversation(id: string) {
  const res = await fetch(`${BASE}/api/conversations/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return handleRes(res);
}
