import { create } from "zustand";
import type { SearchResult, GalaxySubgraph } from "./api";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  toolName?: string;
  createdAt?: string;
}

export interface ConversationItem {
  id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
}

interface AppState {
  // Auth
  token: string | null;
  setToken: (t: string) => void;

  // Conversations
  conversations: ConversationItem[];
  setConversations: (c: ConversationItem[]) => void;
  activeConversationId: string | null;
  setActiveConversationId: (id: string | null) => void;

  // Chat
  messages: ChatMessage[];
  addMessage: (m: ChatMessage) => void;
  setMessages: (m: ChatMessage[]) => void;
  clearChat: () => void;
  isSearching: boolean;
  setIsSearching: (v: boolean) => void;

  // Search results
  searchResults: SearchResult[];
  setSearchResults: (r: SearchResult[]) => void;

  // Mode
  searchMode: "search" | "agent";
  setSearchMode: (m: "search" | "agent") => void;

  // Galaxy
  galaxySubgraph: GalaxySubgraph | null;
  setGalaxySubgraph: (g: GalaxySubgraph | null) => void;
  galaxyFocusedNodeId: number | null;
  setGalaxyFocusedNodeId: (id: number | null) => void;

  // UI
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  rightPanelOpen: boolean;
  setRightPanelOpen: (v: boolean) => void;
  rightTab: "galaxy" | "repos";
  setRightTab: (t: "galaxy" | "repos") => void;
}

export const useStore = create<AppState>((set) => ({
  token: null,
  setToken: (t) => set({ token: t }),

  conversations: [],
  setConversations: (c) => set({ conversations: c }),
  activeConversationId: null,
  setActiveConversationId: (id) => set({ activeConversationId: id }),

  messages: [],
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (m) => set({ messages: m }),
  clearChat: () => set({ messages: [] }),
  isSearching: false,
  setIsSearching: (v) => set({ isSearching: v }),

  searchResults: [],
  setSearchResults: (r) => set({ searchResults: r }),

  searchMode: "search",
  setSearchMode: (m) => set({ searchMode: m }),

  galaxySubgraph: null,
  setGalaxySubgraph: (g) => set({ galaxySubgraph: g }),
  galaxyFocusedNodeId: null,
  setGalaxyFocusedNodeId: (id) => set({ galaxyFocusedNodeId: id }),

  sidebarOpen: false,
  setSidebarOpen: (v) => set({ sidebarOpen: v }),
  rightPanelOpen: false,
  setRightPanelOpen: (v) => set({ rightPanelOpen: v }),
  rightTab: "galaxy",
  setRightTab: (t) => set({ rightTab: t }),
}));
