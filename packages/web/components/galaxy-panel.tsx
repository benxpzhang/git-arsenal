"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { getGalaxyCluster, getGalaxySubgraph, getGalaxyNeighbors, searchGalaxy, type GalaxySubgraph, type GalaxyNode } from "@/lib/api";
import { Globe, RefreshCw, Search, Loader2, Star, Eye, EyeOff } from "lucide-react";
import { useStore } from "@/lib/store";
import { cn } from "@/lib/utils";

const LANG_COLORS: Record<string, string> = {
  Python: "#3572A5", JavaScript: "#f1e05a", TypeScript: "#3178c6",
  Rust: "#dea584", Go: "#00ADD8", Java: "#b07219", "C++": "#f34b7d",
  C: "#555555", Ruby: "#701516", Swift: "#F05138", Kotlin: "#A97BFF",
  Scala: "#c22d40", Shell: "#89e051", Lua: "#000080", PHP: "#4F5D95",
  "C#": "#178600", Dart: "#00B4AB", Elixir: "#6e4a7e", Haskell: "#5e5086",
  R: "#198CE7", Vim: "#199f4b", Zig: "#ec915c", Nix: "#7e7eff",
  Vue: "#41b883", HTML: "#e34c26", CSS: "#563d7c", Jupyter: "#DA5B0B",
};

function getLangColor(lang: string): string {
  return LANG_COLORS[lang] || "#6b7280";
}

/**
 * GitVizz-style edge color: cyan → gold gradient based on similarity.
 * Low sim (~0.1) = rgb(80, 220, 255) cyan
 * High sim (~0.5+) = rgb(255, 200, 55) warm gold
 */
function simToColor(sim: number, alpha?: number): string {
  const t = Math.min(1, Math.max(0, (sim - 0.1) / 0.4));
  const r = Math.round(80 + 175 * t);
  const g = Math.round(220 - 20 * t);
  const b = Math.round(255 - 200 * t);
  if (alpha !== undefined) {
    return `rgba(${r},${g},${b},${alpha.toFixed(2)})`;
  }
  return `rgb(${r},${g},${b})`;
}

function isAdjacentToHover(l: any, hoverId: number | null): boolean {
  if (hoverId === null) return false;
  const src = typeof l.source === "object" ? l.source.id : l.source;
  const tgt = typeof l.target === "object" ? l.target.id : l.target;
  return src === hoverId || tgt === hoverId;
}

interface SearchHit {
  id: number;
  name: string;
  stars: number;
  rawLang: string;
  leafId: number;
  color?: string;
}

export function GalaxyPanel() {
  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [data, setData] = useState<GalaxySubgraph | null>(null);
  const [loading, setLoading] = useState(false);

  // Search state
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [isNavigating, setIsNavigating] = useState(false);
  const searchBoxRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isComposingRef = useRef(false);

  // Visual state — refs for graph callbacks, state for React UI
  const [hiddenLangs, setHiddenLangs] = useState<Set<string>>(new Set());
  const [showLegend, setShowLegend] = useState(true);
  const focusedIdRef = useRef<number | null>(null);
  const hiddenLangsRef = useRef<Set<string>>(new Set());
  const hoverIdRef = useRef<number | null>(null);

  const { setGalaxySubgraph, galaxyFocusedNodeId, setGalaxyFocusedNodeId } = useStore();

  // Sync refs with store state
  useEffect(() => { focusedIdRef.current = galaxyFocusedNodeId; }, [galaxyFocusedNodeId]);
  useEffect(() => { hiddenLangsRef.current = hiddenLangs; }, [hiddenLangs]);

  // When focused node is set externally (from chat/repo list), fly to it
  useEffect(() => {
    if (galaxyFocusedNodeId === null || !data) return;
    const target = data.nodes.find((n) => n.id === galaxyFocusedNodeId);
    if (target) {
      focusedIdRef.current = galaxyFocusedNodeId;
      refreshNodeVisuals();
      flyToNode(target);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [galaxyFocusedNodeId]);

  // ── Language stats from current data ──
  const langStats = useMemo(() => {
    if (!data) return [];
    const counts = new Map<string, number>();
    for (const n of data.nodes) {
      const lang = n.rawLang || "Other";
      counts.set(lang, (counts.get(lang) || 0) + 1);
    }
    return Array.from(counts.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([lang, count]) => ({ lang, count, color: getLangColor(lang) }));
  }, [data]);

  // ── Refresh graph visuals without restarting simulation ──
  const refreshNodeVisuals = useCallback(() => {
    if (!graphRef.current) return;
    graphRef.current
      .nodeColor((n: any) => {
        if (n.id === focusedIdRef.current) return "#ffffff";
        if (hiddenLangsRef.current.has(n.rawLang || "Other")) return n.color || "#6b7280";
        return n.color || "#6b7280";
      })
      .nodeVal((n: any) => {
        const base = n.val || 1;
        if (n.id === focusedIdRef.current) return base * 4;
        return base;
      })
      .nodeVisibility((n: any) => {
        const lang = n.rawLang || "Other";
        return !hiddenLangsRef.current.has(lang);
      });
  }, []);

  const refreshLinkVisuals = useCallback(() => {
    if (!graphRef.current) return;
    const hovering = hoverIdRef.current !== null;
    graphRef.current
      .linkColor((l: any) => {
        const sim = l.sim || 0;
        if (hovering) {
          if (isAdjacentToHover(l, hoverIdRef.current)) {
            return simToColor(sim, 0.4 + 0.5 * Math.min(1, (sim - 0.1) / 0.4));
          }
          return "rgba(0,0,0,0)";
        }
        // Default: all links visible, alpha scales with sim
        const t = Math.min(1, Math.max(0, (sim - 0.1) / 0.4));
        return simToColor(sim, 0.03 + 0.08 * t);
      })
      .linkWidth((l: any) => {
        if (hovering && isAdjacentToHover(l, hoverIdRef.current)) {
          const t = Math.min(1, ((l.sim || 0) - 0.1) / 0.4);
          return 1.5 + 2 * t;
        }
        return 0.4;
      })
      .linkDirectionalParticles((l: any) => {
        if (hovering) {
          return isAdjacentToHover(l, hoverIdRef.current) ? 5 : 0;
        }
        const sim = l.sim || 0;
        return sim > 0.25 ? 2 : 1;
      })
      .linkDirectionalParticleWidth((l: any) => {
        const sim = l.sim || 0;
        if (hovering && isAdjacentToHover(l, hoverIdRef.current)) {
          return 1.2 + sim * 2.5;
        }
        return 0.4 + sim * 1.2;
      })
      .linkDirectionalParticleSpeed((l: any) => {
        const sim = l.sim || 0;
        if (hovering && isAdjacentToHover(l, hoverIdRef.current)) {
          return 0.005 + sim * 0.01;
        }
        return 0.002 + sim * 0.004;
      })
      .linkDirectionalParticleColor((l: any) => {
        const sim = l.sim || 0;
        if (hovering && !isAdjacentToHover(l, hoverIdRef.current)) {
          return "rgba(0,0,0,0)";
        }
        return simToColor(sim);
      })
      .linkVisibility((l: any) => {
        const src = typeof l.source === "object" ? l.source : null;
        const tgt = typeof l.target === "object" ? l.target : null;
        if (src && hiddenLangsRef.current.has(src.rawLang || "Other")) return false;
        if (tgt && hiddenLangsRef.current.has(tgt.rawLang || "Other")) return false;
        return true;
      });
  }, []);

  const flyToNode = useCallback((target: GalaxyNode, duration = 800) => {
    if (!graphRef.current || target.x === undefined || target.y === undefined || target.z === undefined) return;
    const distance = 160;
    const hyp = Math.hypot(target.x, target.y, target.z) || 1;
    const distRatio = 1 + distance / hyp;
    graphRef.current.cameraPosition(
      {
        x: target.x * distRatio,
        y: target.y * distRatio,
        z: target.z * distRatio,
      },
      { x: target.x, y: target.y, z: target.z },
      duration,
    );
  }, []);

  // ── Navigate to repo: load cluster, fly, highlight white ──
  const navigateToRepo = useCallback(async (hit: SearchHit) => {
    setShowDropdown(false);
    setQuery(hit.name);
    setIsNavigating(true);

    try {
      const localMatch = data?.nodes.find((n) => n.id === hit.id);
      if (localMatch) {
        setGalaxyFocusedNodeId(hit.id);
        focusedIdRef.current = hit.id;
        refreshNodeVisuals();
        flyToNode(localMatch);
        return;
      }

      const seeded = await getGalaxySubgraph({ id: hit.id, max_nodes: 500 });
      const clusterId = seeded.leafId;
      const clusterData: GalaxySubgraph =
        typeof clusterId === "number"
          ? await getGalaxyCluster(clusterId, hit.id, 500)
          : seeded;

      setGalaxyFocusedNodeId(hit.id);
      focusedIdRef.current = hit.id;
      setData(clusterData);
      setGalaxySubgraph(clusterData);
    } catch {
      // silently fail
    } finally {
      setIsNavigating(false);
    }
  }, [data, flyToNode, setGalaxySubgraph, refreshNodeVisuals]);

  // ── Debounced search ──
  const doSearch = useCallback(async (q: string) => {
    if (q.length < 2) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }

    setIsSearching(true);
    try {
      const localHits: SearchHit[] = (data?.nodes ?? [])
        .filter((n) => n.name.toLowerCase().includes(q.toLowerCase()))
        .slice(0, 4)
        .map((n) => ({
          id: n.id, name: n.name, stars: n.stars,
          rawLang: n.rawLang, leafId: n.leafId, color: n.color,
        }));

      const remoteRes = await searchGalaxy(q, 10);
      const remoteHits: SearchHit[] = (remoteRes?.results ?? []).map((r: any) => ({
        id: r.id, name: r.name, stars: r.stars,
        rawLang: r.rawLang, leafId: r.leafId, color: r.color,
      }));

      const seenIds = new Set(localHits.map((h) => h.id));
      const merged = [
        ...localHits,
        ...remoteHits.filter((h) => !seenIds.has(h.id)),
      ].slice(0, 10);

      setSearchResults(merged);
      setHighlightIdx(-1);
      setShowDropdown(merged.length > 0);
    } catch {
      setSearchResults([]);
      setShowDropdown(false);
    } finally {
      setIsSearching(false);
    }
  }, [data]);

  function handleQueryChange(value: string) {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (!value.trim()) {
      setSearchResults([]);
      setShowDropdown(false);
      return;
    }
    debounceRef.current = setTimeout(() => doSearch(value.trim()), 280);
  }

  function handleSearchKeyDown(e: React.KeyboardEvent) {
    const nativeEvent = e.nativeEvent as KeyboardEvent;
    if (nativeEvent.isComposing || isComposingRef.current || nativeEvent.keyCode === 229) {
      return;
    }

    if (!showDropdown || searchResults.length === 0) {
      if (e.key === "Enter") {
        e.preventDefault();
        doSearch(query.trim());
      }
      return;
    }

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        setHighlightIdx((prev) => (prev + 1) % searchResults.length);
        break;
      case "ArrowUp":
        e.preventDefault();
        setHighlightIdx((prev) => (prev <= 0 ? searchResults.length - 1 : prev - 1));
        break;
      case "Enter":
        e.preventDefault();
        if (highlightIdx >= 0 && highlightIdx < searchResults.length) {
          navigateToRepo(searchResults[highlightIdx]);
        } else if (searchResults.length > 0) {
          navigateToRepo(searchResults[0]);
        }
        break;
      case "Escape":
        setShowDropdown(false);
        setHighlightIdx(-1);
        break;
    }
  }

  // Click-outside to close dropdown
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // ── Language filter toggle ──
  function toggleLang(lang: string) {
    setHiddenLangs((prev) => {
      const next = new Set(prev);
      if (next.has(lang)) next.delete(lang);
      else next.add(lang);
      hiddenLangsRef.current = next;
      refreshNodeVisuals();
      refreshLinkVisuals();
      return next;
    });
  }

  function showAllLangs() {
    setHiddenLangs(new Set());
    hiddenLangsRef.current = new Set();
    refreshNodeVisuals();
    refreshLinkVisuals();
  }

  function hideAllExcept(lang: string) {
    const allLangs = langStats.map((s) => s.lang);
    const next = new Set(allLangs.filter((l) => l !== lang));
    setHiddenLangs(next);
    hiddenLangsRef.current = next;
    refreshNodeVisuals();
    refreshLinkVisuals();
  }

  // ── Load random cluster ──
  async function loadRandom() {
    setLoading(true);
    try {
      const seed = await getGalaxySubgraph({ random: true, max_nodes: 500 });
      const clusterId = seed.leafId;
      const d =
        typeof clusterId === "number"
          ? await getGalaxyCluster(clusterId, seed.focus, 500)
          : seed;
      setData(d);
      setGalaxySubgraph(d);
      // Highlight the focus node in white
      const focusId = d.focus ?? seed.focus;
      if (typeof focusId === "number") {
        setGalaxyFocusedNodeId(focusId);
        focusedIdRef.current = focusId;
      }
    } catch {
      // silently fail
    }
    setLoading(false);
  }

  useEffect(() => {
    loadRandom();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset hidden langs when data changes
  useEffect(() => {
    setHiddenLangs(new Set());
    hiddenLangsRef.current = new Set();
  }, [data]);

  // ── 3D graph rendering ──
  useEffect(() => {
    if (!data || !containerRef.current) return;

    let destroyed = false;

    (async () => {
      const ForceGraph3DModule = await import("3d-force-graph");
      const ForceGraph3D = ForceGraph3DModule.default;

      if (destroyed || !containerRef.current) return;

      if (graphRef.current) {
        graphRef.current._destructor?.();
      }

      const graph = (ForceGraph3D as any)()(containerRef.current)
        .width(containerRef.current.clientWidth)
        .height(containerRef.current.clientHeight)
        .backgroundColor("rgba(0,0,0,0)")
        .nodeLabel((n: any) => `${n.name} ⭐${n.stars}`)
        .nodeColor((n: any) => {
          if (n.id === focusedIdRef.current) return "#ffffff";
          return n.color || "#6b7280";
        })
        .nodeVal((n: any) => {
          const base = n.val || 1;
          if (n.id === focusedIdRef.current) return base * 4;
          return base;
        })
        .nodeVisibility((n: any) => {
          const lang = n.rawLang || "Other";
          return !hiddenLangsRef.current.has(lang);
        })
        .nodeOpacity(0.9)
        .linkColor((l: any) => {
          const sim = l.sim || 0;
          // Initial load: no hover, show all links with sim-scaled alpha
          const t = Math.min(1, Math.max(0, (sim - 0.1) / 0.4));
          return simToColor(sim, 0.03 + 0.08 * t);
        })
        .linkWidth(0.4)
        .linkDirectionalParticles((l: any) => {
          const sim = l.sim || 0;
          return sim > 0.25 ? 2 : 1;
        })
        .linkDirectionalParticleWidth((l: any) => {
          return 0.4 + (l.sim || 0) * 1.2;
        })
        .linkDirectionalParticleSpeed((l: any) => {
          return 0.002 + (l.sim || 0) * 0.004;
        })
        .linkDirectionalParticleColor((l: any) => {
          return simToColor(l.sim || 0);
        })
        .linkVisibility((l: any) => {
          const src = typeof l.source === "object" ? l.source : null;
          const tgt = typeof l.target === "object" ? l.target : null;
          if (src && hiddenLangsRef.current.has(src.rawLang || "Other")) return false;
          if (tgt && hiddenLangsRef.current.has(tgt.rawLang || "Other")) return false;
          return true;
        })
        .linkOpacity(0.7)
        .enableNodeDrag(false)
        .cooldownTicks(120)
        .onNodeHover((node: any) => {
          hoverIdRef.current = node?.id ?? null;
          if (containerRef.current) {
            containerRef.current.style.cursor = node ? "pointer" : "default";
          }
          if (graphRef.current) {
            refreshLinkVisuals();
          }
        })
        .onNodeClick((node: any) => {
          if (!node) return;
          setGalaxyFocusedNodeId(node.id);
          focusedIdRef.current = node.id;
          refreshNodeVisuals();
          flyToNode(node);

          // Fetch and merge global neighbors for the clicked node
          getGalaxyNeighbors(node.id, 15).then((result) => {
            if (!graphRef.current || !result?.nodes?.length) return;
            const currentData = graphRef.current.graphData();
            const existingIds = new Set(currentData.nodes.map((n: any) => n.id));

            const newNodes = result.nodes.filter((n: any) => !existingIds.has(n.id));
            const newLinks = result.links.filter(
              (l: any) => !currentData.links.some(
                (el: any) => {
                  const es = typeof el.source === "object" ? el.source.id : el.source;
                  const et = typeof el.target === "object" ? el.target.id : el.target;
                  return (es === l.source && et === l.target) || (es === l.target && et === l.source);
                },
              ),
            );

            if (newNodes.length === 0 && newLinks.length === 0) return;

            graphRef.current.graphData({
              nodes: [...currentData.nodes, ...newNodes],
              links: [...currentData.links, ...newLinks],
            });

            // Re-apply visuals after data merge
            setTimeout(() => {
              refreshNodeVisuals();
              refreshLinkVisuals();
            }, 100);
          }).catch(() => {});
        })
        .graphData({
          nodes: data.nodes.map((n) => ({ ...n })),
          links: data.links.map((l) => ({ ...l })),
        });

      graphRef.current = graph;

      // Fly to focused node after physics stabilises; skip zoomToFit to avoid
      // the "zoom-in then zoom-out" flash and excessive whitespace.
      setTimeout(() => {
        const focusId = focusedIdRef.current;
        if (focusId !== null) {
          const target = data.nodes.find((n) => n.id === focusId);
          if (target && target.x !== undefined) {
            flyToNode(target);
            return;
          }
        }
      }, 600);
    })();

    return () => {
      destroyed = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  // ── Resize handler ──
  useEffect(() => {
    function onResize() {
      if (graphRef.current && containerRef.current) {
        graphRef.current
          .width(containerRef.current.clientWidth)
          .height(containerRef.current.clientHeight);
      }
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return (
    <div className="h-full flex flex-col relative">
      {/* Header */}
      <div className="absolute top-4 left-4 right-4 z-20 flex items-center justify-between bg-background/60 backdrop-blur-md border border-border/50 rounded-xl px-4 py-2.5 shadow-sm">
        <div className="text-sm min-w-0">
          {data ? (
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-semibold text-foreground truncate">{data.focusName}</span>
              {data.clusterName && (
                <>
                  <span className="text-muted-foreground/50">•</span>
                  <span className="text-muted-foreground truncate">{data.clusterName}</span>
                </>
              )}
              <span className="text-muted-foreground/40 text-xs">
                {data.nodes.length} repos
              </span>
            </div>
          ) : (
            <span className="text-muted-foreground">Loading galaxy...</span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Search with autocomplete dropdown */}
          <div ref={searchBoxRef} className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            {(isSearching || isNavigating) && (
              <Loader2 className="w-3 h-3 absolute right-2.5 top-1/2 -translate-y-1/2 text-blue-400 animate-spin" />
            )}
            <input
              value={query}
              onChange={(e) => handleQueryChange(e.target.value)}
              onKeyDown={handleSearchKeyDown}
              onCompositionStart={() => { isComposingRef.current = true; }}
              onCompositionEnd={() => { isComposingRef.current = false; }}
              onFocus={() => {
                if (searchResults.length > 0) setShowDropdown(true);
              }}
              placeholder="Search repos..."
              className="h-8 w-56 pl-8 pr-8 text-xs rounded-lg border border-border/60 bg-background/70 outline-none focus:border-blue-400/60 transition-colors"
            />

            {/* Autocomplete dropdown */}
            {showDropdown && searchResults.length > 0 && (
              <div className="absolute top-full left-0 right-0 mt-1 bg-card/95 backdrop-blur-lg border border-border/60 rounded-xl shadow-xl overflow-hidden z-50 max-h-[360px] overflow-y-auto">
                {searchResults.map((hit, idx) => {
                  const isLocal = data?.nodes.some((n) => n.id === hit.id);
                  return (
                    <button
                      key={hit.id}
                      onClick={() => navigateToRepo(hit)}
                      onMouseEnter={() => setHighlightIdx(idx)}
                      className={cn(
                        "w-full text-left px-3 py-2 flex items-center gap-2 text-xs transition-colors",
                        idx === highlightIdx
                          ? "bg-accent text-foreground"
                          : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
                      )}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5">
                          <span className="font-medium text-foreground truncate">{hit.name}</span>
                          {isLocal && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-blue-500/15 text-blue-400 border border-blue-500/20 flex-shrink-0">
                              in view
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 text-[10px] text-muted-foreground/70">
                          {hit.rawLang && (
                            <span className="flex items-center">
                              <span className="inline-block w-2 h-2 rounded-full mr-1" style={{ backgroundColor: getLangColor(hit.rawLang) }} />
                              {hit.rawLang}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-0.5 text-[10px] text-muted-foreground/60 flex-shrink-0">
                        <Star className="w-2.5 h-2.5" />
                        {hit.stars >= 1000 ? `${(hit.stars / 1000).toFixed(1)}k` : hit.stars}
                      </div>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <button
            onClick={() => setShowLegend((v) => !v)}
            className={cn(
              "p-1.5 rounded-lg transition-all",
              showLegend
                ? "text-foreground bg-accent"
                : "text-muted-foreground hover:text-foreground hover:bg-accent",
            )}
            title="Toggle language filter"
          >
            {showLegend ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
          </button>

          <button
            onClick={loadRandom}
            disabled={loading}
            className="p-1.5 text-muted-foreground hover:text-foreground hover:bg-accent rounded-lg transition-all disabled:opacity-30"
            title="Random cluster"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Language Legend / Filter Panel */}
      {showLegend && langStats.length > 0 && (
        <div className="absolute bottom-4 left-4 z-20 bg-background/60 backdrop-blur-md border border-border/50 rounded-xl shadow-sm max-h-[50%] overflow-y-auto w-44">
          <div className="flex items-center justify-between px-3 py-2 border-b border-border/30">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Language</span>
            {hiddenLangs.size > 0 && (
              <button
                onClick={showAllLangs}
                className="text-[9px] text-blue-400 hover:text-blue-300 transition-colors"
              >
                Show all
              </button>
            )}
          </div>
          <div className="py-1">
            {langStats.map(({ lang, count, color }) => {
              const isHidden = hiddenLangs.has(lang);
              return (
                <button
                  key={lang}
                  onClick={() => toggleLang(lang)}
                  onDoubleClick={() => hideAllExcept(lang)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-1 text-[11px] transition-all",
                    isHidden
                      ? "opacity-25 hover:opacity-50"
                      : "opacity-100 hover:bg-accent/30",
                  )}
                  title={isHidden ? `Show ${lang}` : `Hide ${lang} · Double-click: show only ${lang}`}
                >
                  <span
                    className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0 transition-all", isHidden && "grayscale")}
                    style={{ backgroundColor: color }}
                  />
                  <span className="flex-1 text-left truncate text-foreground/80">{lang}</span>
                  <span className="text-muted-foreground/50 tabular-nums">{count}</span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Navigating overlay */}
      {isNavigating && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/30 backdrop-blur-sm pointer-events-none">
          <div className="flex items-center gap-3 bg-card/90 border border-border/50 rounded-xl px-5 py-3 shadow-lg">
            <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
            <span className="text-sm text-foreground">Loading cluster...</span>
          </div>
        </div>
      )}

      {/* Focused node indicator */}
      {galaxyFocusedNodeId !== null && data && (
        <div className="absolute bottom-4 right-4 z-20 bg-background/60 backdrop-blur-md border border-border/50 rounded-xl px-3 py-2 shadow-sm">
          <div className="flex items-center gap-2 text-xs">
            <span className="w-2.5 h-2.5 rounded-full bg-white shadow-[0_0_6px_rgba(255,255,255,0.8)]" />
            <span className="text-foreground font-medium truncate max-w-[200px]">
              {data.nodes.find((n) => n.id === galaxyFocusedNodeId)?.name || ""}
            </span>
            <button
              onClick={() => {
                setGalaxyFocusedNodeId(null);
                focusedIdRef.current = null;
                refreshNodeVisuals();
              }}
              className="text-muted-foreground/50 hover:text-foreground text-[10px] ml-1"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* 3D Canvas */}
      <div ref={containerRef} className="flex-1 relative bg-[#050505]">
        {!data && !loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <Globe className="w-8 h-8 opacity-50" />
          </div>
        )}
      </div>
    </div>
  );
}
