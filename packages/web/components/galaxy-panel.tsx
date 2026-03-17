"use client";

import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { getGalaxyCluster, getGalaxySubgraph, getGalaxyNeighbors, getGalaxyDetail, searchGalaxy, type GalaxySubgraph } from "@/lib/api";
import { Globe, RefreshCw, Search, Loader2, Star, Eye, EyeOff, X } from "lucide-react";
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

const EXTERNAL_LABEL = "⚡ External";

function getLangColor(lang: string): string {
  return LANG_COLORS[lang] || "#6b7280";
}

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
}

export function GalaxyPanel() {
  const { galaxySubgraph, setGalaxySubgraph, galaxyFocusedNodeId, setGalaxyFocusedNodeId } = useStore();

  const containerRef = useRef<HTMLDivElement>(null);
  const graphRef = useRef<any>(null);
  const [data, setData] = useState<GalaxySubgraph | null>(galaxySubgraph);
  const [loading, setLoading] = useState(false);
  const [containerReady, setContainerReady] = useState(false);

  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchHit[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [showDropdown, setShowDropdown] = useState(false);
  const [highlightIdx, setHighlightIdx] = useState(-1);
  const [isNavigating, setIsNavigating] = useState(false);
  const searchBoxRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isComposingRef = useRef(false);

  const [hiddenLangs, setHiddenLangs] = useState<Set<string>>(new Set());
  const [showLegend, setShowLegend] = useState(true);
  const [externalCount, setExternalCount] = useState(0);
  const focusedIdRef = useRef<number | null>(null);
  const hiddenLangsRef = useRef<Set<string>>(new Set());
  const hoverIdRef = useRef<number | null>(null);
  const popoverRef = useRef<HTMLDivElement>(null);
  const [focusedWikiText, setFocusedWikiText] = useState<string>("");

  useEffect(() => { hiddenLangsRef.current = hiddenLangs; }, [hiddenLangs]);

  useEffect(() => {
    focusedIdRef.current = galaxyFocusedNodeId;
    if (galaxyFocusedNodeId === null) return;

    // If node is already in current graph, just fly to it
    const gd = graphRef.current?.graphData();
    const target = gd?.nodes?.find((n: any) => n.id === galaxyFocusedNodeId);
    if (target) {
      refreshNodeVisuals();
      flyToNode(target);
      return;
    }

    // Node not in current view — load its cluster
    (async () => {
      try {
        const seeded = await getGalaxySubgraph({ id: galaxyFocusedNodeId, max_nodes: 500 });
        const clusterId = seeded.leafId;
        const clusterData: GalaxySubgraph =
          typeof clusterId === "number"
            ? await getGalaxyCluster(clusterId, galaxyFocusedNodeId, 500)
            : seeded;
        setData(clusterData);
        setGalaxySubgraph(clusterData);
      } catch {
        // silently fail
      }
    })();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [galaxyFocusedNodeId]);

  useEffect(() => {
    if (galaxyFocusedNodeId === null) { setFocusedWikiText(""); return; }
    let cancelled = false;
    getGalaxyDetail(galaxyFocusedNodeId).then((d) => {
      if (!cancelled) setFocusedWikiText(d?.wiki_text || "");
    }).catch(() => { if (!cancelled) setFocusedWikiText(""); });
    return () => { cancelled = true; };
  }, [galaxyFocusedNodeId]);

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

  const refreshNodeVisuals = useCallback(() => {
    if (!graphRef.current) return;
    graphRef.current
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
        if (n._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
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
            return simToColor(sim, 0.5 + 0.4 * Math.min(1, (sim - 0.1) / 0.4));
          }
          return "rgba(0,0,0,0)";
        }
        const t = Math.min(1, Math.max(0, (sim - 0.1) / 0.4));
        return simToColor(sim, 0.04 + 0.08 * t);
      })
      .linkWidth((l: any) => {
        if (hovering && isAdjacentToHover(l, hoverIdRef.current)) {
          const t = Math.min(1, ((l.sim || 0) - 0.1) / 0.4);
          return 1.0 + 1.5 * t;
        }
        return 0.3;
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
          return 1.5 + sim * 3;
        }
        return 0.5 + sim * 1.5;
      })
      .linkDirectionalParticleSpeed((l: any) => {
        const sim = l.sim || 0;
        if (hovering && isAdjacentToHover(l, hoverIdRef.current)) {
          return 0.004 + sim * 0.008;
        }
        return 0.001 + sim * 0.003;
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
        if (src && src._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
        if (tgt && tgt._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
        if (src && hiddenLangsRef.current.has(src.rawLang || "Other")) return false;
        if (tgt && hiddenLangsRef.current.has(tgt.rawLang || "Other")) return false;
        return true;
      });
  }, []);

  const flyToNode = useCallback((target: any, duration = 600) => {
    if (!graphRef.current || target.x === undefined || target.y === undefined) return;
    graphRef.current.centerAt(target.x, target.y, duration);
    graphRef.current.zoom(4, duration);
  }, []);

  const navigateToRepo = useCallback(async (hit: SearchHit) => {
    setShowDropdown(false);
    setQuery(hit.name);
    setIsNavigating(true);

    try {
      const gd = graphRef.current?.graphData();
      const localMatch = gd?.nodes?.find((n: any) => n.id === hit.id);
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
  }, [flyToNode, setGalaxySubgraph, refreshNodeVisuals, setGalaxyFocusedNodeId]);

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
        .map((n) => ({ id: n.id, name: n.name, stars: n.stars, rawLang: n.rawLang }));

      const remoteRes = await searchGalaxy(q, 10);
      const remoteHits: SearchHit[] = (remoteRes?.results ?? []).map((r: any) => ({
        id: r.id, name: r.name, stars: r.stars, rawLang: r.rawLang,
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

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (searchBoxRef.current && !searchBoxRef.current.contains(e.target as Node)) {
        setShowDropdown(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

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
    if (!data) loadRandom();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setHiddenLangs(new Set());
    hiddenLangsRef.current = new Set();
    if (data && data.leafId !== undefined) {
      const extCnt = data.nodes.filter((n) => n.leafId !== data.leafId).length;
      setExternalCount(extCnt);
    } else {
      setExternalCount(0);
    }
  }, [data]);

  // ── 2D graph rendering ──
  useEffect(() => {
    if (!data || !containerRef.current || !containerReady) return;
    if (containerRef.current.clientWidth === 0 || containerRef.current.clientHeight === 0) return;

    let destroyed = false;

    (async () => {
      const ForceGraphModule = await import("force-graph");
      const ForceGraph = ForceGraphModule.default;

      if (destroyed || !containerRef.current) return;

      if (graphRef.current) {
        graphRef.current._destructor?.();
      }

      const graph = (ForceGraph as any)()(containerRef.current)
        .width(containerRef.current.clientWidth)
        .height(containerRef.current.clientHeight)
        .backgroundColor("rgba(0,0,0,0)")
        .autoPauseRedraw(false)
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
          if (n._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
          const lang = n.rawLang || "Other";
          return !hiddenLangsRef.current.has(lang);
        })
        .nodeCanvasObjectMode(() => "replace")
        .nodeCanvasObject((n: any, ctx: CanvasRenderingContext2D, globalScale: number) => {
          const isFocused = n.id === focusedIdRef.current;
          const isHovered = n.id === hoverIdRef.current;
          const isExternal = !!n._isExternal;
          
          const baseR = Math.sqrt(n.val || 1) * 3;
          const r = isFocused ? baseR * 2 : baseR;

          if (isExternal && !isFocused) {
            const d = r * 1.3;
            ctx.beginPath();
            ctx.moveTo(n.x, n.y - d);
            ctx.lineTo(n.x + d, n.y);
            ctx.lineTo(n.x, n.y + d);
            ctx.lineTo(n.x - d, n.y);
            ctx.closePath();
            ctx.fillStyle = n.color || "#6b7280";
            ctx.fill();
          } else {
            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
            ctx.fillStyle = isFocused ? "#ffffff" : (n.color || "#6b7280");
            ctx.fill();
          }

          if (isFocused || isHovered) {
            ctx.strokeStyle = isFocused ? "rgba(255,255,255,0.5)" : "#ffffff";
            ctx.lineWidth = 2 / globalScale;
            ctx.beginPath();
            ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
            ctx.stroke();
          }

          if (globalScale > 2 || isFocused) {
            const label = n.name;
            const fontSize = Math.max(10 / globalScale, 2);
            ctx.font = `${isFocused ? "bold " : ""}${fontSize}px 'Inter', system-ui, sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "top";

            const yOff = r + 4 / globalScale;

            ctx.fillStyle = isFocused ? "#ffffff" : "rgba(255,255,255,0.4)";
            ctx.fillText(label, n.x, n.y + yOff);
          }
        })
        .nodeLabel((n: any) => {
          if (hoverIdRef.current !== n.id) return "";
          const extBadge = n._isExternal
            ? `<span style="display:inline-block;background:#f59e0b22;color:#f59e0b;font-size:9px;padding:1px 5px;border-radius:4px;border:1px solid #f59e0b44;margin-left:4px;">External</span>`
            : "";
          const isWiki = !!n.wiki;
          const snippet = n.wiki || n.desc || "";
          const tagStyle = isWiki
            ? "background:#3b82f622;color:#60a5fa;border:1px solid #3b82f633;"
            : "background:#71717a22;color:#a1a1aa;border:1px solid #71717a33;";
          const tagLabel = isWiki ? "DeepWiki" : "GitHub Desc";
          const snippetHtml = snippet
            ? `<div style="margin-top:6px"><span style="display:inline-block;font-size:9px;padding:1px 5px;border-radius:4px;${tagStyle}">${tagLabel}</span><div class="text-xs text-muted-foreground/80 mt-1 leading-relaxed" style="display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden">${snippet.replace(/</g, '&lt;').replace(/>/g, '&gt;')}</div></div>`
            : "";
          return `
            <div class="bg-card/90 backdrop-blur-md border border-border/50 rounded-xl p-3 shadow-xl max-w-[320px] pointer-events-none">
              <div class="flex items-start justify-between gap-3 mb-1">
                <div class="font-semibold text-foreground text-sm break-all leading-tight">${n.name}${extBadge}</div>
              </div>
              <div class="flex items-center gap-3 text-xs text-muted-foreground mt-1.5">
                <div class="flex items-center gap-1.5">
                  <span class="w-2 h-2 rounded-full" style="background-color: ${n.color || '#888'}"></span>
                  ${n.rawLang || 'Unknown'}
                </div>
                <div class="flex items-center gap-1">
                  <svg class="w-3.5 h-3.5 text-yellow-500 fill-yellow-500" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon></svg>
                  ${n.stars?.toLocaleString() || 0}
                </div>
              </div>
              ${snippetHtml}
            </div>
          `;
        })
        .linkColor((l: any) => {
          const sim = l.sim || 0;
          const t = Math.min(1, Math.max(0, (sim - 0.1) / 0.4));
          return simToColor(sim, 0.04 + 0.08 * t);
        })
        .linkWidth(0.3)
        .linkDirectionalParticles((l: any) => {
          const sim = l.sim || 0;
          return sim > 0.25 ? 2 : 1;
        })
        .linkDirectionalParticleWidth((l: any) => {
          return 0.5 + (l.sim || 0) * 1.5;
        })
        .linkDirectionalParticleSpeed((l: any) => {
          return 0.001 + (l.sim || 0) * 0.003;
        })
        .linkDirectionalParticleColor((l: any) => {
          return simToColor(l.sim || 0);
        })
        .linkVisibility((l: any) => {
          const src = typeof l.source === "object" ? l.source : null;
          const tgt = typeof l.target === "object" ? l.target : null;
          if (src && src._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
          if (tgt && tgt._isExternal && hiddenLangsRef.current.has(EXTERNAL_LABEL)) return false;
          if (src && hiddenLangsRef.current.has(src.rawLang || "Other")) return false;
          if (tgt && hiddenLangsRef.current.has(tgt.rawLang || "Other")) return false;
          return true;
        })
        .enableNodeDrag(true)
        .cooldownTicks(150)
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

          // Unpin previously focused node
          if (focusedIdRef.current !== null && focusedIdRef.current !== node.id) {
            const gd = graphRef.current?.graphData();
            const prev = gd?.nodes?.find((n: any) => n.id === focusedIdRef.current);
            if (prev) { prev.fx = undefined; prev.fy = undefined; }
          }

          setGalaxyFocusedNodeId(node.id);
          focusedIdRef.current = node.id;

          // Pin the clicked node so force simulation won't push it away
          node.fx = node.x;
          node.fy = node.y;

          refreshNodeVisuals();
          flyToNode(node);

          getGalaxyNeighbors(node.id, 15).then((result) => {
            if (!graphRef.current || !result?.nodes?.length) return;
            const currentData = graphRef.current.graphData();
            const existingIds = new Set(currentData.nodes.map((n: any) => n.id));

            const newNodes = result.nodes
              .filter((n: any) => !existingIds.has(n.id))
              .map((n: any) => {
                const ox = n.x ?? 0;
                const oy = n.y ?? 0;
                const oz = n.z ?? 0;
                const px = (ox + oz * 0.5) * 8;
                const py = (oy + oz * 0.5) * 8;
                return { ...n, x: px, y: py, _isExternal: true };
              });
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
            graphRef.current.d3ReheatSimulation();

            if (newNodes.length > 0) {
              setExternalCount((prev) => prev + newNodes.length);
            }

            setTimeout(() => {
              refreshNodeVisuals();
              refreshLinkVisuals();
              // Re-center on pinned node after simulation settles
              const gd = graphRef.current?.graphData();
              const target = gd?.nodes?.find((nd: any) => nd.id === focusedIdRef.current);
              if (target) flyToNode(target, 400);
            }, 300);
          }).catch(() => {});
        })
        .onRenderFramePre((ctx: CanvasRenderingContext2D, globalScale: number) => {
          if (globalScale < 0.3) return;
          const { width: w, height: h } = ctx.canvas;
          const spacing = 24;
          const dotR = 0.8;
          ctx.fillStyle = "rgba(255,255,255,0.04)";
          const transform = (graphRef.current as any)?._zoom?.();
          if (transform) {
            const sx = transform.x;
            const sy = transform.y;
            const sk = transform.k;
            const startX = Math.floor(-sx / sk / spacing) * spacing;
            const startY = Math.floor(-sy / sk / spacing) * spacing;
            const endX = startX + w / sk + spacing * 2;
            const endY = startY + h / sk + spacing * 2;
            const maxDots = 120;
            const cols = Math.ceil((endX - startX) / spacing);
            const rows = Math.ceil((endY - startY) / spacing);
            if (cols * rows > maxDots * maxDots) return;
            for (let x = startX; x < endX; x += spacing) {
              for (let y = startY; y < endY; y += spacing) {
                ctx.beginPath();
                ctx.arc(x, y, dotR / sk, 0, 2 * Math.PI);
                ctx.fill();
              }
            }
          }
        })
        .onRenderFramePost(() => {
          if (focusedIdRef.current === null || !popoverRef.current || !graphRef.current || !containerRef.current) return;
          const gd = graphRef.current.graphData();
          const target = gd?.nodes?.find((n: any) => n.id === focusedIdRef.current);
          if (target && target.x !== undefined && target.y !== undefined) {
            const coords = graphRef.current.graph2ScreenCoords(target.x, target.y);
            const rect = containerRef.current.getBoundingClientRect();
            const screenX = coords.x + rect.left;
            const screenY = coords.y + rect.top;

            const popW = popoverRef.current.offsetWidth;
            const popH = popoverRef.current.offsetHeight;
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            let px = screenX + 20;
            let py = screenY - 20;
            if (px + popW > vw - 8) px = screenX - popW - 20;
            if (py + popH > vh - 8) py = vh - popH - 8;
            if (py < 8) py = 8;

            popoverRef.current.style.left = `${px}px`;
            popoverRef.current.style.top = `${py}px`;
          }
        })
        .graphData({
          nodes: data.nodes.map((n) => {
            const ox = n.x ?? 0;
            const oy = n.y ?? 0;
            const oz = n.z ?? 0;
            const px = (ox + oz * 0.5) * 8;
            const py = (oy + oz * 0.5) * 8;
            const isExt = data.leafId != null && n.leafId !== data.leafId;
            return { ...n, x: px, y: py, _isExternal: isExt };
          }),
          links: data.links.map((l) => ({ ...l })),
        });

      graphRef.current = graph;

      // Configure d3 forces after graph is created
      graph.d3Force('center', null);
      const chargeForce = graph.d3Force('charge');
      if (chargeForce) chargeForce.strength(-150).distanceMax(400);
      const linkForce = graph.d3Force('link');
      if (linkForce) linkForce.distance(50).strength(0.3);

      setTimeout(() => {
        const focusId = focusedIdRef.current;
        if (focusId !== null) {
          const gd = graphRef.current?.graphData();
          const target = gd?.nodes?.find((nd: any) => nd.id === focusId);
          if (target && target.x !== undefined) {
            flyToNode(target);
            return;
          }
        }
        if (graphRef.current?.zoomToFit) {
          graphRef.current.zoomToFit(600, 60);
        }
      }, 500);
    })();

    return () => {
      destroyed = true;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, containerReady]);

  useEffect(() => {
    if (!containerRef.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) {
          setContainerReady(true);
          if (graphRef.current) {
            graphRef.current.width(width).height(height);
          }
        }
      }
    });
    ro.observe(containerRef.current);
    return () => ro.disconnect();
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
            {externalCount > 0 && (() => {
              const isHidden = hiddenLangs.has(EXTERNAL_LABEL);
              return (
                <button
                  key={EXTERNAL_LABEL}
                  onClick={() => toggleLang(EXTERNAL_LABEL)}
                  className={cn(
                    "w-full flex items-center gap-2 px-3 py-1 text-[11px] transition-all border-b border-border/20 mb-0.5",
                    isHidden
                      ? "opacity-25 hover:opacity-50"
                      : "opacity-100 hover:bg-accent/30",
                  )}
                  title={isHidden ? "Show external nodes" : "Hide external (out-of-cluster) nodes"}
                >
                  <svg className={cn("w-2.5 h-2.5 flex-shrink-0 transition-all", isHidden && "opacity-30")} viewBox="0 0 10 10">
                    <polygon points="5,0 10,5 5,10 0,5" fill="white" />
                  </svg>
                  <span className="flex-1 text-left truncate text-foreground/80">External</span>
                  <span className="text-muted-foreground/50 tabular-nums">{externalCount}</span>
                </button>
              );
            })()}
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

      {/* 2D Canvas */}
      <div ref={containerRef} className="flex-1 relative bg-[#0a0a0f]">
        {!data && !loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <Globe className="w-8 h-8 opacity-50" />
          </div>
        )}
      </div>

      {/* Following Popover for focused node */}
      {galaxyFocusedNodeId !== null && data && (
          (() => {
            const gd = graphRef.current?.graphData();
            const focusedNode = gd?.nodes?.find((n: any) => n.id === galaxyFocusedNodeId)
              || data.nodes.find((n) => n.id === galaxyFocusedNodeId);
            if (!focusedNode) return null;
            const similarRepos: { id: number; name: string; color: string; rawLang: string; stars: number; sim: number }[] = [];
            if (gd?.links) {
              for (const l of gd.links) {
                const srcId = typeof l.source === "object" ? l.source.id : l.source;
                const tgtId = typeof l.target === "object" ? l.target.id : l.target;
                const sim = l.sim || 0;
                if (sim <= 0) continue;
                let neighborId: number | null = null;
                if (srcId === galaxyFocusedNodeId) neighborId = tgtId;
                else if (tgtId === galaxyFocusedNodeId) neighborId = srcId;
                if (neighborId === null) continue;
                const neighbor = gd.nodes.find((n: any) => n.id === neighborId);
                if (neighbor) {
                  similarRepos.push({
                    id: neighbor.id,
                    name: neighbor.name,
                    color: neighbor.color || '#888',
                    rawLang: neighbor.rawLang || 'Unknown',
                    stars: neighbor.stars || 0,
                    sim,
                  });
                }
              }
              similarRepos.sort((a, b) => b.stars - a.stars);
            }

            return (
              <div 
                ref={popoverRef}
                className="fixed z-50 bg-card/90 backdrop-blur-md border border-border/50 rounded-xl shadow-xl w-80 pointer-events-auto"
                style={{ left: '-9999px', top: '-9999px' }}
              >
                <div className="p-3 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h3 className="font-semibold text-foreground text-sm leading-tight break-words">
                        {focusedNode.name}
                      </h3>
                      {focusedNode._isExternal && (
                        <span className="inline-block mt-1 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20">
                          External
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      <a
                        href={`https://github.com/${focusedNode.name}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-muted-foreground hover:text-primary transition-colors p-1 rounded-md hover:bg-accent"
                        title="Open in GitHub"
                      >
                        <Globe className="w-3.5 h-3.5" />
                      </a>
                      <button
                        onClick={() => {
                          // Unpin the node
                          const gd = graphRef.current?.graphData();
                          const prev = gd?.nodes?.find((nd: any) => nd.id === galaxyFocusedNodeId);
                          if (prev) { prev.fx = undefined; prev.fy = undefined; }
                          setGalaxyFocusedNodeId(null);
                          focusedIdRef.current = null;
                          refreshNodeVisuals();
                        }}
                        className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-md hover:bg-accent"
                        title="Close"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                  
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
                    <div className="flex items-center gap-1.5">
                      <span 
                        className="w-2 h-2 rounded-full" 
                        style={{ backgroundColor: focusedNode.color || '#888' }}
                      />
                      {focusedNode.rawLang || 'Unknown'}
                    </div>
                    <div className="flex items-center gap-1">
                      <Star className="w-3 h-3 text-yellow-500 fill-yellow-500" />
                      {focusedNode.stars?.toLocaleString() || 0}
                    </div>
                  </div>

                  {(() => {
                    const isWiki = !!(focusedWikiText || focusedNode.wiki);
                    const text = focusedWikiText || focusedNode.wiki || focusedNode.desc;
                    if (!text) return null;
                    return (
                      <div className="space-y-1.5">
                        <span className={cn(
                          "inline-block text-[9px] px-1.5 py-0.5 rounded font-medium border",
                          isWiki
                            ? "bg-blue-500/10 text-blue-400 border-blue-500/20"
                            : "bg-zinc-500/10 text-zinc-400 border-zinc-500/20"
                        )}>
                          {isWiki ? "DeepWiki" : "GitHub Desc"}
                        </span>
                        <div className="max-h-[200px] overflow-y-auto text-xs text-muted-foreground/80 leading-relaxed whitespace-pre-line">
                          {text}
                        </div>
                      </div>
                    );
                  })()}
                </div>

                {similarRepos.length > 0 && (
                  <div className="border-t border-border/30">
                    <div className="px-3 py-1.5">
                      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Similar Repos</span>
                    </div>
                    <div className="max-h-[200px] overflow-y-auto pb-1.5">
                      {similarRepos.slice(0, 10).map((repo) => (
                        <button
                          key={repo.id}
                          onClick={() => {
                            setGalaxyFocusedNodeId(repo.id);
                            focusedIdRef.current = repo.id;
                            refreshNodeVisuals();
                            const target = gd?.nodes?.find((n: any) => n.id === repo.id);
                            if (target) flyToNode(target);
                          }}
                          className="w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-accent/30 transition-colors"
                        >
                          <span
                            className="w-2 h-2 rounded-full flex-shrink-0"
                            style={{ backgroundColor: repo.color }}
                          />
                          <span className="flex-1 text-left truncate text-foreground/80">{repo.name}</span>
                          <span className="text-[10px] text-muted-foreground/60 flex-shrink-0">
                            ★ {repo.stars >= 1000 ? `${(repo.stars / 1000).toFixed(1)}k` : repo.stars}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })()
        )}
    </div>
  );
}
