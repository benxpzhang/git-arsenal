"use client";

import { useStore } from "@/lib/store";
import { GalaxyPanel } from "@/components/galaxy-panel";
import { RepoListPanel } from "@/components/repo-list-panel";
import { cn } from "@/lib/utils";
import { Globe, List, X } from "lucide-react";

export function RightPanel() {
  const { rightTab, setRightTab, searchResults, rightPanelOpen, setRightPanelOpen } = useStore();

  return (
    <div className={cn(
      "border-l border-border/50 flex flex-col flex-shrink-0 bg-card/30 transition-all duration-300 ease-in-out",
      rightPanelOpen
        ? "w-[60vw] min-w-[520px] max-w-[60vw] opacity-100"
        : "w-0 opacity-0 overflow-hidden border-none pointer-events-none"
    )}>
      {/* Tabs */}
      <div className="px-4 py-3 border-b border-border/50 flex items-center justify-between bg-background/50 backdrop-blur-sm">
        <div className="flex items-center bg-secondary/50 p-1 rounded-lg">
          <button
            onClick={() => setRightTab("galaxy")}
            className={cn(
              "flex items-center gap-1.5 text-[13px] font-medium px-4 py-1.5 rounded-md transition-all",
              rightTab === "galaxy"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Globe className="w-3.5 h-3.5" />
            Galaxy
          </button>
          <button
            onClick={() => setRightTab("repos")}
            className={cn(
              "flex items-center gap-1.5 text-[13px] font-medium px-4 py-1.5 rounded-md transition-all",
              rightTab === "repos"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <List className="w-3.5 h-3.5" />
            Repos {searchResults.length > 0 && <span className="ml-1 opacity-70">({searchResults.length})</span>}
          </button>
        </div>
        <button 
          onClick={() => setRightPanelOpen(false)}
          className="p-1.5 text-muted-foreground hover:text-foreground rounded-lg hover:bg-accent transition-colors"
          title="Close Panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Panel Content */}
      <div className="flex-1 overflow-hidden">
        {rightTab === "galaxy" ? <GalaxyPanel /> : <RepoListPanel />}
      </div>
    </div>
  );
}
