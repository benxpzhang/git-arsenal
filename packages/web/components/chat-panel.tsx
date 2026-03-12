"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { Send, Search, Sparkles, Loader2, StopCircle } from "lucide-react";
import { useStore, type ChatMessage } from "@/lib/store";
import {
  searchRepos,
  getConversation,
  createConversation,
  addMessage as apiAddMessage,
} from "@/lib/api";
import { streamAgent, type AcpEvent } from "@/lib/acp-client";
import { SEARCH_MODE_SYSTEM_PROMPT, SEARCH_MODE_CONSTRAINTS } from "@/lib/prompts";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";

export function ChatPanel() {
  const {
    messages,
    addMessage,
    setMessages,
    clearChat,
    isSearching,
    setIsSearching,
    setSearchResults,
    searchMode,
    setSearchMode,
    activeConversationId,
    setActiveConversationId,
    conversations,
    setConversations,
    setRightPanelOpen,
    setRightTab,
    sidebarOpen,
    searchResults: storeSearchResults,
    setGalaxyFocusedNodeId,
  } = useStore();

  const [input, setInput] = useState("");
  const [streamingText, setStreamingText] = useState("");
  const [agentStatus, setAgentStatus] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isComposingRef = useRef(false);

  // Auto-scroll on new messages or streaming text
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingText]);

  // Load messages when active conversation changes.
  // Skip if messages are already present (e.g., we just created this conversation
  // and added messages locally — avoids a race where the backend fetch overwrites
  // the local messages).
  useEffect(() => {
    if (!activeConversationId) return;
    // If local messages already exist for this session, don't overwrite them.
    if (messages.length > 0) return;

    const targetId = activeConversationId;
    getConversation(targetId)
      .then((data) => {
        // Stale check: user may have switched conversations while we were loading
        if (useStore.getState().activeConversationId !== targetId) return;
        // Double-check messages are still empty (another message could have arrived)
        if (useStore.getState().messages.length > 0) return;
        if (data && data.messages) {
          setMessages(
            data.messages.map(
              (m: {
                id: string;
                role: string;
                content: string;
                tool_name?: string;
                created_at: string;
              }) => ({
                id: m.id,
                role: m.role as "user" | "assistant" | "tool" | "system",
                content: m.content,
                toolName: m.tool_name,
                createdAt: m.created_at,
              }),
            ),
          );
        }
      })
      .catch(() => {
        // Silently fail
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeConversationId]);

  // ── Direct search handler ──
  const handleDirectSearch = useCallback(
    async (q: string) => {
      try {
        let convId = activeConversationId;
        if (!convId) {
          // Use the query as the conversation title (truncated) instead of "New Chat"
          const conv = await createConversation(q.slice(0, 60));
          convId = conv.id;
          setActiveConversationId(convId);
          setConversations([{ ...conv, title: q.slice(0, 60) }, ...conversations]);
        }

        if (convId) await apiAddMessage(convId, "user", q).catch(() => {});

        const data = await searchRepos(q);
        setSearchResults(data.results);

        const resultText =
          data.results.length > 0
            ? `Found **${data.results.length}** repositories matching your query. Here are the top results:\n\n` +
              data.results
                .slice(0, 5)
                .map(
                  (r, i) =>
                    `${i + 1}. **[${r.full_name}](${r.html_url})** ⭐ ${r.stars.toLocaleString()}\n   ${r.description || "No description"}\n   _${r.language || "Unknown"} · Score: ${(r.score * 100).toFixed(1)}%_`,
                )
                .join("\n\n") +
              (data.results.length > 5
                ? `\n\n...and ${data.results.length - 5} more in the panel →`
                : "")
            : "No repositories found matching your query. Try a different description.";

        const assistantMsg: ChatMessage = {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: resultText,
        };
        addMessage(assistantMsg);

        if (convId) await apiAddMessage(convId, "assistant", resultText).catch(() => {});
        // Do not open right panel automatically
      } catch (e: unknown) {
        const errMsg = e instanceof Error ? e.message : "Search failed";
        addMessage({
          id: `err-${Date.now()}`,
          role: "assistant",
          content: `Sorry, the search failed: ${errMsg}. Please try again.`,
        });
      }
    },
    [
      activeConversationId,
      conversations,
      addMessage,
      setSearchResults,
      setActiveConversationId,
      setConversations,
    ],
  );

  // ── Agent search handler ──
  const handleAgentSearch = useCallback(
    async (q: string, mcpOnly = false) => {
      try {
        let convId = activeConversationId;
        let isNewConv = false;
        if (!convId) {
          isNewConv = true;
          const conv = await createConversation(q.slice(0, 60));
          convId = conv.id;
          setActiveConversationId(convId);
          setConversations([{ ...conv, title: q.slice(0, 60) }, ...conversations]);
        }

        if (convId) await apiAddMessage(convId, "user", q).catch(() => {});

        let queryForAgent = q;
        if (mcpOnly) {
          const prefix = isNewConv ? `${SEARCH_MODE_SYSTEM_PROMPT}\n\n---\n\n` : "";
          queryForAgent = `${prefix}${q}\n\n${SEARCH_MODE_CONSTRAINTS}`;
        }

        // Start streaming
        const ctrl = new AbortController();
        abortRef.current = ctrl;
        let fullText = "";
        let fallbackToDirect = false;
        setStreamingText("");
        setAgentStatus("Connecting to agent...");

        for await (const evt of streamAgent(queryForAgent, convId || undefined, ctrl.signal)) {
          switch (evt.type) {
            case "text":
              fullText += evt.text;
              setStreamingText(fullText);
              setAgentStatus(null);
              break;

            case "status":
              setAgentStatus(evt.text);
              break;

            case "permission":
              // Show tool usage
              setAgentStatus(
                evt.approved
                  ? `🔧 Using ${evt.tool.replace("mcp__git-arsenal__", "")}...`
                  : `⛔ Blocked: ${evt.tool}`,
              );
              break;

            case "error":
              // If agent produced meaningful text before erroring, keep it
              if (fullText.trim()) {
                fullText += `\n\n⚠️ ${evt.text}`;
                setStreamingText(fullText);
              } else {
                // No text yet — agent backend is unavailable, fall back to direct search
                fallbackToDirect = true;
                setAgentStatus("Falling back to direct search...");
                if (abortRef.current) {
                  abortRef.current.abort();
                  abortRef.current = null;
                }
              }
              break;

            case "log":
              // Skip noise like <tool-progress> tags
              // Show meaningful tool results as status so user sees progress
              if (evt.text && !evt.text.includes("<tool-progress>")) {
                // Extract first line as a brief summary
                const firstLine = evt.text.split("\n")[0].slice(0, 100);
                if (firstLine.trim()) {
                  setAgentStatus(`📋 ${firstLine}`);
                }
              }
              break;

            case "done":
              break;
          }
        }

        // Finalize
        abortRef.current = null;
        setStreamingText("");
        setAgentStatus(null);

        if (fallbackToDirect) {
          await handleDirectSearch(q);
          return;
        }

        if (fullText.trim()) {
          const assistantMsg: ChatMessage = {
            id: `agent-${Date.now()}`,
            role: "assistant",
            content: fullText,
          };
          addMessage(assistantMsg);
          if (convId) await apiAddMessage(convId, "assistant", fullText).catch(() => {});
        } else {
          addMessage({
            id: `err-${Date.now()}`,
            role: "assistant",
            content:
              "Agent returned no response. The model may not be configured. Check server logs.",
          });
        }
      } catch {
        // Agent completely unavailable — fall back to direct search silently
        setStreamingText("");
        setAgentStatus("Agent unavailable, falling back to direct search...");
        abortRef.current = null;
        try {
          await handleDirectSearch(q);
        } catch {
          addMessage({
            id: `err-${Date.now()}`,
            role: "assistant",
            content: "Search failed. Please check your connection and try again.",
          });
        }
        setAgentStatus(null);
      }
    },
    [
      activeConversationId,
      conversations,
      addMessage,
      handleDirectSearch,
      setActiveConversationId,
      setConversations,
    ],
  );

  // ── Unified submit ──
  async function handleSearch() {
    const q = input.trim();
    if (!q || isSearching) return;

    setInput("");
    setIsSearching(true);

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: q,
    };
    addMessage(userMsg);

    try {
      if (searchMode === "search") {
        await handleAgentSearch(q, true);
      } else {
        await handleAgentSearch(q, false);
      }
    } finally {
      setIsSearching(false);
    }
  }

  // ── Stop agent ──
  function handleStop() {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    const nativeEvent = e.nativeEvent as KeyboardEvent;
    if (nativeEvent.isComposing || isComposingRef.current || nativeEvent.keyCode === 229) {
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSearch();
    }
  }

  // Intercept links in markdown
  const markdownComponents = {
    a: ({ href, children }: any) => {
      return (
        <a
          href={href}
          onClick={(e) => {
            e.preventDefault();
            // Try to find the repo in search results by URL match
            const match = storeSearchResults.find(
              (r) => r.html_url === href || r.full_name === String(children),
            );
            if (match) {
              setGalaxyFocusedNodeId(match.id);
            }
            setRightPanelOpen(true);
            setRightTab("galaxy");
          }}
          className="text-blue-400 hover:underline cursor-pointer"
        >
          {children}
        </a>
      );
    },
  };

  const isHomeMode =
    !activeConversationId && messages.length === 0 && !streamingText && !isSearching;

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 relative bg-background">
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-10 px-4 py-3 flex items-center justify-between bg-background/80 backdrop-blur-sm border-b border-border/50">
        <div className="flex items-center gap-2">
          {!sidebarOpen && (
            <span className="text-sm font-semibold ml-2">Git Arsenal</span>
          )}
        </div>
        <div className="flex items-center gap-1 bg-secondary/50 rounded-lg p-0.5">
          <button
            onClick={() => setSearchMode("search")}
            className={cn(
              "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors",
              searchMode === "search"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Search className="w-3.5 h-3.5" /> Search
          </button>
          <button
            disabled
            className={cn(
              "flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md transition-colors cursor-not-allowed",
              searchMode === "agent"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground/40",
            )}
          >
            <Sparkles className="w-3.5 h-3.5" /> Agent
          </button>
        </div>
      </div>

      {/* Messages Area */}
      <div 
        ref={scrollRef} 
        className={cn(
          "flex-1 min-h-0 overflow-y-auto px-4 pt-16 pb-32 space-y-6 scroll-smooth",
          isHomeMode ? "flex flex-col items-center justify-center" : ""
        )}
      >
        {isHomeMode ? (
          <div className="w-full max-w-2xl flex flex-col items-center justify-center space-y-8 mt-[-10vh]">
            <div className="text-center space-y-3">
              <h1 className="text-3xl font-semibold tracking-tight">What are you looking for?</h1>
              <p className="text-muted-foreground">
                Search across 150,000+ open-source repositories using natural language.
              </p>
            </div>
            
            {/* Suggestions */}
            <div className="flex flex-wrap justify-center gap-2 max-w-lg">
              {["Rust web frameworks", "Python data visualization", "React state management", "Go terminal UI"].map(
                (suggestion) => (
                <button
                  key={suggestion}
                  onClick={() => {
                    setInput(suggestion);
                    // Optional: auto-submit
                    // handleSearch(suggestion);
                  }}
                  className="px-4 py-2 rounded-full border border-border/50 bg-card/50 text-sm text-muted-foreground hover:text-foreground hover:bg-accent hover:border-border transition-all"
                >
                  {suggestion}
                </button>
                ),
              )}
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full space-y-6">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={cn(
                  "flex",
                  msg.role === "user" ? "justify-end" : "justify-start",
                )}
              >
                <div
                  className={cn(
                    "max-w-[85%] rounded-2xl px-5 py-4 text-[15px] leading-relaxed overflow-hidden",
                    msg.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "bg-card/50 border border-border/50 shadow-sm",
                  )}
                >
                  {msg.role === "user" ? (
                    <p>{msg.content}</p>
                  ) : (
                    <div className="prose prose-sm prose-invert max-w-none overflow-x-auto">
                      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                        {msg.content}
                      </ReactMarkdown>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Streaming text (agent mode) */}
            {streamingText && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl px-5 py-4 text-[15px] leading-relaxed bg-card/50 border border-border/50 shadow-sm overflow-hidden">
                  <div className="prose prose-sm prose-invert max-w-none overflow-x-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
                      {streamingText}
                    </ReactMarkdown>
                  </div>
                </div>
              </div>
            )}

            {/* Agent status indicator */}
            {agentStatus && (
              <div className="flex items-center gap-2 text-sm text-blue-400/70 py-1 px-3">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{agentStatus}</span>
              </div>
            )}

            {/* Search mode searching indicator */}
            {isSearching && !streamingText && !agentStatus && (
              <div className="flex justify-start">
                <div className="bg-card/50 border border-border/50 shadow-sm rounded-2xl px-5 py-4 text-[15px]">
                  <div className="flex items-center gap-3 text-muted-foreground">
                    <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                    Searching repositories...
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Floating Input Area */}
      <div className={cn(
        "absolute left-0 right-0 px-4 transition-all duration-500 ease-in-out",
        isHomeMode ? "bottom-[30%] translate-y-1/2" : "bottom-0 pb-6 pt-4 bg-gradient-to-t from-background via-background to-transparent"
      )}>
        <div className="max-w-3xl mx-auto w-full relative">
          <div className="flex items-end gap-2 bg-card border border-border/60 shadow-lg rounded-2xl px-4 py-3 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 transition-all">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onCompositionStart={() => {
                isComposingRef.current = true;
              }}
              onCompositionEnd={() => {
                isComposingRef.current = false;
              }}
              onKeyDown={handleKeyDown}
              placeholder={
                searchMode === "search"
                  ? "Search with MCP-only agent workflow..."
                  : "Agent mode (coming soon)..."
              }
              className="flex-1 bg-transparent outline-none text-[15px] text-foreground placeholder:text-muted-foreground resize-none min-h-[24px] max-h-[200px] py-1"
              rows={1}
              disabled={isSearching}
              style={{ height: "auto" }}
              onInput={(e) => {
                const target = e.target as HTMLTextAreaElement;
                target.style.height = "auto";
                target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
              }}
            />

            {/* Stop/Send button */}
            <div className="flex-shrink-0 mb-0.5">
              {isSearching && searchMode === "search" && abortRef.current ? (
                <button
                  onClick={handleStop}
                  className="p-2 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded-xl transition-colors"
                  title="Stop agent"
                >
                  <StopCircle className="w-5 h-5" />
                </button>
              ) : (
                <button
                  onClick={handleSearch}
                  disabled={!input.trim() || isSearching}
                  className="p-2 text-primary hover:text-primary-foreground hover:bg-primary disabled:text-muted-foreground disabled:hover:bg-transparent disabled:opacity-50 rounded-xl transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              )}
            </div>
          </div>

          {/* Mode indicator */}
          {!isHomeMode && (
            <div className="absolute -bottom-6 left-2 flex items-center gap-2">
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
              Search
            </span>
              <span className="text-[10px] text-muted-foreground/70">
              MCP-only tools enabled to avoid disabled tool interruptions
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
