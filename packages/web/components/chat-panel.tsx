"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useChat } from "@ai-sdk/react";
import { Send, Search, Sparkles, Loader2, StopCircle, Database, Layout, Cpu, Terminal, Hexagon } from "lucide-react";
import { useStore } from "@/lib/store";
import {
  createConversation,
  addMessage as apiAddMessage,
  searchGalaxy,
} from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { motion, AnimatePresence } from "framer-motion";
import { RepoCards, parseRepoCards, type RepoCardData } from "./repo-cards";

const EXAMPLE_QUERIES = [
  "一个能把 PDF、网页接入 LLM 的 RAG 知识库平台，支持多轮对话",
  "Self-hosted Notion alternative with real-time collaboration",
  "用 Rust 写的高性能 Web 框架，类似 Express 或 Gin 的开发体验",
  "AI coding assistant that runs in the terminal with local models",
];

export function ChatPanel() {
  const {
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
    setMessages: setStoreMessages,
    clearChat,
  } = useStore();

  const scrollRef = useRef<HTMLDivElement>(null);
  const isComposingRef = useRef(false);
  const convIdRef = useRef<string | null>(activeConversationId);
  const [placeholderIdx, setPlaceholderIdx] = useState(0);

  useEffect(() => {
    convIdRef.current = activeConversationId;
  }, [activeConversationId]);

  const [localInput, setLocalInput] = useState("");

  const {
    messages,
    sendMessage,
    status,
    stop,
    setMessages,
    error,
  } = useChat({
    api: "/api/chat",
    onFinish: async (message) => {
      const convId = convIdRef.current;
      if (convId && message.role === "assistant") {
        const textContent = typeof message.content === "string"
          ? message.content
          : message.parts
              ?.filter((p): p is { type: "text"; text: string } => p.type === "text")
              .map((p) => p.text)
              .join("") || "";
        if (textContent) {
          await apiAddMessage(convId, "assistant", textContent).catch(() => {});
        }
      }
    },
  });

  const isLoading = status === "submitted" || status === "streaming";

  // Placeholder rotation
  useEffect(() => {
    if (isLoading || localInput) return;
    const interval = setInterval(() => {
      setPlaceholderIdx((prev) => (prev + 1) % EXAMPLE_QUERIES.length);
    }, 4000);
    return () => clearInterval(interval);
  }, [isLoading, localInput]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const q = localInput.trim();
      if (!q || isLoading) return;

      let convId = convIdRef.current;
      if (!convId) {
        try {
          const conv = await createConversation(q.slice(0, 60));
          convId = conv.id;
          convIdRef.current = convId;
          setActiveConversationId(convId);
          setConversations([
            { ...conv, title: q.slice(0, 60) },
            ...conversations,
          ]);
        } catch {
          // proceed without conversation persistence
        }
      }

      if (convId) {
        await apiAddMessage(convId, "user", q).catch(() => {});
      }

      setLocalInput("");
      sendMessage({ text: q });
    },
    [
      localInput,
      isLoading,
      sendMessage,
      conversations,
      setActiveConversationId,
      setConversations,
    ],
  );

  function handleKeyDown(e: React.KeyboardEvent) {
    const nativeEvent = e.nativeEvent as KeyboardEvent;
    if (
      nativeEvent.isComposing ||
      isComposingRef.current ||
      nativeEvent.keyCode === 229
    ) {
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  const markdownComponents = {
    a: ({ href, children }: any) => (
      <a
        href={href}
        onClick={(e) => {
          e.preventDefault();

          const match = storeSearchResults.find(
            (r) =>
              r.html_url === href || r.full_name === String(children),
          );
          if (match) {
            setGalaxyFocusedNodeId(match.id);
            setRightPanelOpen(true);
            setRightTab("galaxy");
            return;
          }

          // Extract repo full_name from GitHub URL (e.g. https://github.com/owner/repo)
          const ghMatch = href?.match(/github\.com\/([^/]+\/[^/]+)/);
          const repoName = ghMatch?.[1] ?? String(children).trim();
          if (repoName && repoName.includes("/")) {
            searchGalaxy(repoName, 5).then((res) => {
              const hit = (res?.results ?? []).find(
                (r: any) =>
                  r.name === repoName ||
                  r.name?.toLowerCase() === repoName.toLowerCase(),
              );
              if (hit) {
                setGalaxyFocusedNodeId(hit.id);
                setRightPanelOpen(true);
                setRightTab("galaxy");
              } else if (href?.startsWith("http")) {
                window.open(href, "_blank", "noopener");
              }
            }).catch(() => {
              if (href?.startsWith("http")) {
                window.open(href, "_blank", "noopener");
              }
            });
            return;
          }

          if (href?.startsWith("http")) {
            window.open(href, "_blank", "noopener");
          }
        }}
        className="text-blue-400 hover:underline cursor-pointer"
      >
        {children}
      </a>
    ),
  };

  const isHomeMode =
    !activeConversationId && messages.length === 0 && !isLoading;

  const getMessageText = (msg: typeof messages[0]): string => {
    if (typeof msg.content === "string" && msg.content) return msg.content;
    return (
      msg.parts
        ?.filter((p): p is { type: "text"; text: string } => p.type === "text")
        .map((p) => p.text)
        .join("") || ""
    );
  };

  return (
    <div className="flex-1 flex flex-col min-w-0 min-h-0 relative bg-background">
      {/* Header */}
      <div className="absolute top-0 left-0 right-0 z-10 px-4 py-3 flex items-center justify-between bg-background/80 backdrop-blur-sm border-b border-border/50">
        <div className="flex items-center gap-2">
          {!sidebarOpen && (
            <div className="flex items-center gap-2 ml-2">
              <div className="bg-primary/20 p-1 rounded-md">
                <Hexagon className="w-3.5 h-3.5 text-primary fill-primary/40" />
              </div>
              <span className="text-sm font-bold tracking-tight">
                Git<span className="font-medium text-muted-foreground">Arsenal</span>
              </span>
            </div>
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
          isHomeMode ? "flex flex-col items-center justify-center" : "",
        )}
      >
        {isHomeMode ? (
          <div className="w-full max-w-2xl flex flex-col items-center justify-center mt-[-15vh]">
            <div className="text-center space-y-4">
              <h1 className="text-4xl sm:text-5xl font-bold tracking-tight bg-gradient-to-br from-foreground to-muted-foreground bg-clip-text text-transparent">
                Don't reinvent. <span className="text-primary">Rediscover.</span>
              </h1>
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full space-y-6">
            {messages
              .filter((msg) => msg.role === "user" || msg.role === "assistant")
              .map((msg) => {
                if (msg.role === "user") {
                  const text = getMessageText(msg);
                  if (!text) return null;
                  return (
                    <div key={msg.id} className="flex justify-end">
                      <div className="max-w-[85%] rounded-2xl px-5 py-4 text-[15px] leading-relaxed overflow-hidden bg-primary text-primary-foreground">
                        <p>{text}</p>
                      </div>
                    </div>
                  );
                }

                const parts = msg.parts ?? [];
                const textParts: string[] = [];
                const cardSets: RepoCardData[][] = [];
                let hasToolPending = false;

                for (const part of parts) {
                  const p = part as any;
                  if (p.type === "text") {
                    textParts.push(p.text ?? "");
                  } else if (
                    p.type === "dynamic-tool" &&
                    (p.toolName === "search_repos" || p.toolName === "get_repo_detail")
                  ) {
                    if (p.state === "output-available" && p.output) {
                      const cards = parseRepoCards(p.output);
                      if (cards) cardSets.push(cards);
                    } else if (p.state !== "output-available") {
                      hasToolPending = true;
                    }
                  }
                }

                const text = textParts.join("");
                if (!text && cardSets.length === 0 && !hasToolPending) return null;

                return (
                  <div key={msg.id} className="flex justify-start">
                    <div className="max-w-[85%] rounded-2xl px-5 py-4 text-[15px] leading-relaxed overflow-hidden bg-card/50 border border-border/50 shadow-sm space-y-3">
                      {hasToolPending && cardSets.length === 0 && (
                        <div className="flex items-center gap-2 text-sm text-blue-400/70">
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          <span>Searching repositories...</span>
                        </div>
                      )}
                      {cardSets.map((cards, i) => (
                        <RepoCards key={i} repos={cards} />
                      ))}
                      {text && (
                        <div className="prose prose-sm prose-invert max-w-none overflow-x-auto">
                          <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            components={markdownComponents}
                          >
                            {text}
                          </ReactMarkdown>
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}

            {/* Loading indicator */}
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-blue-400/70 py-1 px-3">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Searching repositories...</span>
              </div>
            )}

            {/* Error display */}
            {error && (
              <div className="flex justify-start">
                <div className="max-w-[85%] rounded-2xl px-5 py-4 text-[15px] bg-red-500/10 border border-red-500/30 text-red-300">
                  Error: {error.message}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Floating Input Area */}
      <div
        className={cn(
          "absolute left-0 right-0 px-4 transition-all duration-500 ease-in-out",
          isHomeMode
            ? "top-1/2 -translate-y-1/2 mt-4"
            : "bottom-0 pb-6 pt-4 bg-gradient-to-t from-background via-background to-transparent",
        )}
      >
        <div className="max-w-3xl mx-auto w-full relative">
          <form
            onSubmit={handleSubmit}
            className="flex items-end gap-2 bg-card border border-border/60 shadow-lg rounded-2xl px-4 py-3 focus-within:border-blue-500/50 focus-within:ring-1 focus-within:ring-blue-500/20 transition-all z-10"
          >
            <div className="relative flex-1 min-w-0 flex items-center">
              <textarea
                value={localInput}
                onChange={(e) => setLocalInput(e.target.value)}
                onCompositionStart={() => {
                  isComposingRef.current = true;
                }}
                onCompositionEnd={() => {
                  isComposingRef.current = false;
                }}
                onKeyDown={handleKeyDown}
                placeholder="Ask anything about open source..."
                className="w-full bg-transparent outline-none text-[15px] text-foreground placeholder:text-muted-foreground/40 resize-none min-h-[24px] max-h-[200px] py-1"
                rows={1}
                disabled={isLoading}
                style={{ height: "auto" }}
                onInput={(e) => {
                  const target = e.target as HTMLTextAreaElement;
                  target.style.height = "auto";
                  target.style.height = `${Math.min(target.scrollHeight, 200)}px`;
                }}
              />
            </div>

            <div className="flex-shrink-0 mb-0.5">
              {isLoading ? (
                <button
                  type="button"
                  onClick={stop}
                  className="p-2 text-red-400 hover:text-red-300 hover:bg-red-400/10 rounded-xl transition-colors"
                  title="Stop"
                >
                  <StopCircle className="w-5 h-5" />
                </button>
              ) : (
                <button
                  type="submit"
                  disabled={!localInput.trim() || isLoading}
                  className="p-2 text-primary hover:text-primary-foreground hover:bg-primary disabled:text-muted-foreground disabled:hover:bg-transparent disabled:opacity-50 rounded-xl transition-colors"
                >
                  <Send className="w-5 h-5" />
                </button>
              )}
            </div>
          </form>

          {!isHomeMode && (
            <div className="absolute -bottom-6 left-2 flex items-center gap-2">
              <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">
                AI SDK + MCP
              </span>
              <span className="text-[10px] text-muted-foreground/70">
                Powered by Vercel AI SDK with MCP tools
              </span>
            </div>
          )}

          {isHomeMode && !localInput && !isLoading && (
            <div className="absolute top-full left-0 right-0 mt-3 flex justify-center overflow-hidden h-[90px] pointer-events-none">
              <div className="relative w-full max-w-xl">
                {/* Top and bottom fade masks */}
                <div className="absolute inset-x-0 top-0 h-6 bg-gradient-to-b from-background to-transparent z-10" />
                <div className="absolute inset-x-0 bottom-0 h-6 bg-gradient-to-t from-background to-transparent z-10" />
                
                <AnimatePresence mode="popLayout">
                  <motion.div
                    key={placeholderIdx}
                    initial={{ y: 30, opacity: 0 }}
                    animate={{ y: 0, opacity: 1 }}
                    exit={{ y: -30, opacity: 0 }}
                    transition={{ duration: 0.5, ease: "easeInOut" }}
                    className="absolute inset-0 flex flex-col items-center justify-center gap-2.5"
                  >
                    {/* Previous item (faded) */}
                    <div className="text-[13px] text-muted-foreground/10 truncate w-full text-center px-4 font-medium">
                      {EXAMPLE_QUERIES[(placeholderIdx - 1 + EXAMPLE_QUERIES.length) % EXAMPLE_QUERIES.length]}
                    </div>
                    {/* Current item (clickable) */}
                    <button
                      onClick={() => setLocalInput(EXAMPLE_QUERIES[placeholderIdx])}
                      className="text-[14px] text-muted-foreground/70 hover:text-primary transition-colors truncate w-full text-center px-4 pointer-events-auto font-medium"
                    >
                      {EXAMPLE_QUERIES[placeholderIdx]}
                    </button>
                    {/* Next item (faded) */}
                    <div className="text-[13px] text-muted-foreground/10 truncate w-full text-center px-4 font-medium">
                      {EXAMPLE_QUERIES[(placeholderIdx + 1) % EXAMPLE_QUERIES.length]}
                    </div>
                  </motion.div>
                </AnimatePresence>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
