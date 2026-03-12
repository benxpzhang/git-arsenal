"use client";

import { useStore } from "@/lib/store";
import { Star, ExternalLink, ChevronDown, ChevronUp, Code, Crosshair } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

export function RepoListPanel() {
  const { searchResults, galaxySubgraph, setGalaxyFocusedNodeId, setRightTab } = useStore();
  const clusterRepos =
    galaxySubgraph?.nodes.map((n) => ({
      id: n.id,
      score: 1,
      full_name: n.name,
      stars: n.stars || 0,
      language: n.rawLang || "",
      description: "",
      html_url: n.url || "",
      tree_text: "",
      source: "cluster" as const,
    })) ?? [];

  const repos =
    clusterRepos.length > 0
      ? clusterRepos
      : searchResults.map((r) => ({ ...r, source: "search" as const }));

  if (repos.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-muted-foreground text-sm">
        <div className="text-center space-y-2">
          <Code className="w-8 h-8 mx-auto opacity-50" />
          <p>Search results will appear here</p>
        </div>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto h-full p-3 space-y-2">
      {repos.map((repo, idx) => (
        <RepoCard
          key={repo.id}
          repo={repo}
          rank={idx + 1}
          onLocate={() => {
            setGalaxyFocusedNodeId(repo.id);
            setRightTab("galaxy");
          }}
        />
      ))}
    </div>
  );
}

function RepoCard({
  repo,
  rank,
  onLocate,
}: {
  repo: {
    id: number;
    score?: number;
    full_name: string;
    stars: number;
    language: string;
    description?: string;
    html_url?: string;
    tree_text?: string;
    source?: "cluster" | "search";
  };
  rank: number;
  onLocate?: () => void;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-card/50 border border-border/50 rounded-xl p-4 hover:border-border hover:bg-card transition-all shadow-sm group">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] font-medium text-muted-foreground bg-accent/50 px-1.5 py-0.5 rounded-md flex-shrink-0">
            #{rank}
          </span>
          <a
            href={repo.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[15px] font-semibold text-blue-400 hover:text-blue-300 hover:underline truncate transition-colors"
          >
            {repo.full_name}
          </a>
        </div>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all flex-shrink-0">
          {onLocate && (
            <button
              onClick={onLocate}
              className="p-1 text-muted-foreground hover:text-blue-400 rounded transition-colors"
              title="Locate in Galaxy"
            >
              <Crosshair className="w-4 h-4" />
            </button>
          )}
          <a
            href={repo.html_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-1 text-muted-foreground hover:text-foreground rounded transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
          </a>
        </div>
      </div>

      {/* Description */}
      {repo.description && (
        <p className="text-[13px] text-muted-foreground/90 line-clamp-2 mb-3 leading-relaxed">{repo.description}</p>
      )}

      {/* Meta */}
      <div className="flex items-center gap-4 text-xs text-muted-foreground font-medium">
        <span className="flex items-center gap-1.5 text-yellow-500/90">
          <Star className="w-3.5 h-3.5 fill-current" /> {repo.stars.toLocaleString()}
        </span>
        {repo.language && (
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-blue-400 shadow-[0_0_4px_rgba(96,165,250,0.5)]" />
            {repo.language}
          </span>
        )}
        <span className={cn(
          "px-1.5 py-0.5 rounded-md bg-background/50 border border-border/50",
          (repo.score ?? 0) >= 0.6 ? "text-green-400" : (repo.score ?? 0) >= 0.4 ? "text-yellow-400" : "text-muted-foreground"
        )}>
          {repo.source === "cluster" ? "Cluster" : `${((repo.score ?? 0) * 100).toFixed(0)}% match`}
        </span>
      </div>

      {/* Tree (expandable) */}
      {repo.tree_text && (
        <div className="mt-3 pt-3 border-t border-border/50">
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            Directory tree
          </button>
          {expanded && (
            <pre className="mt-2 text-[11px] text-muted-foreground/80 bg-background/80 rounded-lg p-3 overflow-x-auto font-mono leading-relaxed max-h-60 overflow-y-auto border border-border/50 shadow-inner">
              {repo.tree_text}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
