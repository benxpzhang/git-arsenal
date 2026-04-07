"use client";

import { useState } from "react";
import { Star, ExternalLink, ChevronLeft, ChevronRight } from "lucide-react";
import { useStore } from "@/lib/store";
import { searchGalaxy } from "@/lib/api";

export interface RepoCardData {
  full_name: string;
  stars: number;
  language: string;
  description: string;
  html_url: string;
}

function formatStars(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(n);
}

const LANG_COLORS: Record<string, string> = {
  Python: "bg-blue-500/20 text-blue-300",
  TypeScript: "bg-blue-400/20 text-blue-200",
  JavaScript: "bg-yellow-500/20 text-yellow-300",
  Rust: "bg-orange-500/20 text-orange-300",
  Go: "bg-cyan-500/20 text-cyan-300",
  Java: "bg-red-500/20 text-red-300",
  "C++": "bg-purple-500/20 text-purple-300",
  C: "bg-gray-500/20 text-gray-300",
  Ruby: "bg-red-400/20 text-red-200",
  Shell: "bg-green-500/20 text-green-300",
  Jupyter: "bg-orange-400/20 text-orange-200",
  "Jupyter Notebook": "bg-orange-400/20 text-orange-200",
};

function RepoCard({ repo }: { repo: RepoCardData }) {
  const {
    setGalaxyFocusedNodeId,
    setRightPanelOpen,
    setRightTab,
    searchResults: storeSearchResults,
  } = useStore();

  const langClass =
    LANG_COLORS[repo.language] || "bg-muted-foreground/20 text-muted-foreground";

  function handleClick() {
    const match = storeSearchResults.find(
      (r) => r.full_name === repo.full_name,
    );
    if (match) {
      setGalaxyFocusedNodeId(match.id);
      setRightPanelOpen(true);
      setRightTab("galaxy");
      return;
    }

    searchGalaxy(repo.full_name, 5)
      .then((res) => {
        const hit = (res?.results ?? []).find(
          (r: any) =>
            r.name === repo.full_name ||
            r.name?.toLowerCase() === repo.full_name.toLowerCase(),
        );
        if (hit) {
          setGalaxyFocusedNodeId(hit.id);
          setRightPanelOpen(true);
          setRightTab("galaxy");
        } else if (repo.html_url) {
          window.open(repo.html_url, "_blank", "noopener");
        }
      })
      .catch(() => {
        if (repo.html_url) {
          window.open(repo.html_url, "_blank", "noopener");
        }
      });
  }

  return (
    <div
      onClick={handleClick}
      className="group flex flex-col gap-1.5 px-4 py-3 rounded-xl bg-secondary/40 border border-border/40 hover:border-primary/40 hover:bg-secondary/60 cursor-pointer transition-all"
    >
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-medium text-sm text-foreground truncate">
          {repo.full_name}
        </span>
        <a
          href={repo.html_url}
          target="_blank"
          rel="noopener noreferrer"
          onClick={(e) => e.stopPropagation()}
          className="flex-shrink-0 opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
        >
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1 text-xs text-yellow-400/80">
          <Star className="w-3 h-3 fill-yellow-400/60" />
          {formatStars(repo.stars)}
        </span>
        {repo.language && (
          <span
            className={`text-xs px-1.5 py-0.5 rounded-md font-medium ${langClass}`}
          >
            {repo.language}
          </span>
        )}
      </div>
      {repo.description && (
        <p className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
          {repo.description}
        </p>
      )}
    </div>
  );
}

const PAGE_SIZE = 5;

export function RepoCards({ repos }: { repos: RepoCardData[] }) {
  const [page, setPage] = useState(0);

  if (!repos.length) return null;

  const totalPages = Math.ceil(repos.length / PAGE_SIZE);
  const start = page * PAGE_SIZE;
  const visible = repos.slice(start, start + PAGE_SIZE);

  return (
    <div className="w-full space-y-2">
      <div className="grid gap-2">
        {visible.map((repo) => (
          <RepoCard key={repo.full_name} repo={repo} />
        ))}
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-[11px] text-muted-foreground/60">
            {start + 1}-{Math.min(start + PAGE_SIZE, repos.length)} / {repos.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page === totalPages - 1}
              className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

const REPO_CARDS_REGEX = /<!--REPO_CARDS:(.*?)-->/s;

/**
 * Extract structured repo card data from a tool invocation result.
 * The result may be a string, an MCP content array, or a nested object.
 */
export function parseRepoCards(raw: unknown): RepoCardData[] | null {
  const text = extractText(raw);
  if (!text) return null;
  const m = text.match(REPO_CARDS_REGEX);
  if (!m) return null;
  try {
    const arr = JSON.parse(m[1]);
    if (Array.isArray(arr) && arr.length > 0) return arr;
  } catch {}
  return null;
}

function extractText(raw: unknown): string {
  if (typeof raw === "string") return raw;
  if (Array.isArray(raw)) {
    return raw
      .filter((c: any) => c?.type === "text" && typeof c.text === "string")
      .map((c: any) => c.text)
      .join("\n");
  }
  if (raw && typeof raw === "object") {
    const obj = raw as any;
    if (Array.isArray(obj.content)) return extractText(obj.content);
    if (typeof obj.text === "string") return obj.text;
  }
  return typeof raw === "object" ? JSON.stringify(raw) : String(raw ?? "");
}
