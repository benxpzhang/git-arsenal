"use client";

import { useEffect } from "react";
import { Plus, MessageSquare, Trash2, PanelLeftClose, PanelLeft, PanelRight, Home } from "lucide-react";
import { useStore, type ConversationItem } from "@/lib/store";
import { listConversations, deleteConversation } from "@/lib/api";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const {
    conversations,
    setConversations,
    activeConversationId,
    setActiveConversationId,
    clearChat,
    setSearchResults,
    sidebarOpen,
    setSidebarOpen,
    rightPanelOpen,
    setRightPanelOpen,
    setRightTab,
  } = useStore();

  useEffect(() => {
    loadConversations();
  }, []);

  async function loadConversations() {
    try {
      const list = await listConversations();
      setConversations(list);
    } catch {
      // Silently fail
    }
  }

  function handleNew() {
    // Don't create a server-side conversation until the user actually sends a message.
    // This avoids orphan "New Chat" entries if the user clicks New Chat but never types.
    clearChat();
    setSearchResults([]);
    setActiveConversationId(null);
    setRightPanelOpen(false);
  }

  async function handleSelect(conv: ConversationItem) {
    clearChat();
    setSearchResults([]);
    setActiveConversationId(conv.id);
    setRightPanelOpen(false);
  }

  async function handleDelete(e: React.MouseEvent, convId: string) {
    e.stopPropagation();
    try {
      await deleteConversation(convId);
      const updated = conversations.filter((c) => c.id !== convId);
      setConversations(updated);
      if (activeConversationId === convId) {
        setActiveConversationId(null);
        clearChat();
        setSearchResults([]);
        setRightPanelOpen(false);
      }
    } catch {
      // Silently fail
    }
  }

  function handleHome() {
    setActiveConversationId(null);
    clearChat();
    setSearchResults([]);
    setRightPanelOpen(false);
  }

  if (!sidebarOpen) {
    return (
      <div className="w-14 border-r border-border/50 flex flex-col items-center py-4 gap-2.5 bg-card/40 backdrop-blur-md">
        <button
          onClick={() => setSidebarOpen(true)}
          className="w-9 h-9 inline-flex items-center justify-center rounded-xl text-muted-foreground hover:text-foreground hover:bg-accent/70 transition-all"
          title="Open Sidebar"
        >
          <PanelLeft className="w-5 h-5" />
        </button>
        <button
          onClick={() => {
            setRightPanelOpen(!rightPanelOpen);
            if (!rightPanelOpen) setRightTab("galaxy");
          }}
          className={cn(
            "w-9 h-9 inline-flex items-center justify-center rounded-xl border transition-all shadow-sm",
            rightPanelOpen
              ? "bg-accent border-border text-foreground"
              : "border-border/60 bg-background/70 text-muted-foreground hover:text-foreground hover:border-border hover:bg-accent",
          )}
          title={rightPanelOpen ? "Hide Results Panel" : "Show Results Panel"}
        >
          <PanelRight className="w-5 h-5" />
        </button>
        <button
          onClick={handleNew}
          className="w-9 h-9 inline-flex items-center justify-center rounded-xl border border-border/60 bg-background/70 text-muted-foreground hover:text-foreground hover:border-border hover:bg-accent transition-all shadow-sm"
          title="New Chat"
        >
          <Plus className="w-5 h-5" />
        </button>
      </div>
    );
  }

  return (
    <div className="w-64 border-r border-border/50 flex flex-col bg-card/40 backdrop-blur-md flex-shrink-0">
      {/* Header */}
      <div className="px-4 py-4 flex items-center justify-between border-b border-border/40">
        <button
          onClick={handleHome}
          className="flex items-center gap-2 text-[15px] font-semibold hover:opacity-80 transition-opacity"
        >
          <Home className="w-4 h-4" />
          Git Arsenal
        </button>
        <button
          onClick={() => setSidebarOpen(false)}
          className="w-8 h-8 inline-flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/70 transition-all"
          title="Collapse Sidebar"
        >
          <PanelLeft className="w-4 h-4" />
        </button>
      </div>

      {/* New Chat Button */}
      <div className="px-3 pb-2">
        <button
          onClick={handleNew}
          className="w-full flex items-center gap-2 text-sm px-3 py-2.5 rounded-xl bg-primary/10 text-primary hover:bg-primary/20 transition-colors font-medium"
        >
          <Plus className="w-4 h-4" />
          New Chat
        </button>
      </div>

      {/* Conversation List */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        <div className="px-2 pb-2 text-xs font-medium text-muted-foreground">Recent</div>
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => handleSelect(conv)}
            className={cn(
              "group flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer text-sm transition-all relative",
              activeConversationId === conv.id
                ? "bg-accent text-accent-foreground font-medium"
                : "hover:bg-accent/50 text-muted-foreground"
            )}
          >
            {activeConversationId === conv.id && (
              <div className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-4 bg-primary rounded-r-full" />
            )}
            <MessageSquare className="w-4 h-4 flex-shrink-0 opacity-70" />
            <span className="flex-1 truncate">{conv.title || "Untitled"}</span>
            <button
              onClick={(e) => handleDelete(e, conv.id)}
              className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 hover:bg-red-400/10 rounded-md transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
      
      {/* Bottom User Area */}
      <div className="p-4 border-t border-border/50 bg-background/30">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-gradient-to-tr from-blue-500 to-purple-500 flex items-center justify-center text-white font-medium text-xs shadow-inner">
            U
          </div>
          <div className="flex flex-col">
            <span className="text-sm font-medium">Anonymous</span>
            <span className="text-xs text-muted-foreground">Free Tier</span>
          </div>
        </div>
      </div>
    </div>
  );
}
