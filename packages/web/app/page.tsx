"use client";

import { useEffect, useState } from "react";
import { ensureAuth } from "@/lib/auth";
import { Sidebar } from "@/components/sidebar";
import { ChatPanel } from "@/components/chat-panel";
import { RightPanel } from "@/components/right-panel";
import { AlertCircle, RefreshCw } from "lucide-react";

export default function HomePage() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    ensureAuth()
      .then(() => setReady(true))
      .catch(() => setError(true));
  }, []);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-center space-y-4">
          <AlertCircle className="w-12 h-12 text-red-400 mx-auto" />
          <h2 className="text-xl font-semibold">Connection Failed</h2>
          <p className="text-muted-foreground text-sm">Unable to connect to the backend server.</p>
          <button
            onClick={() => {
              setError(false);
              ensureAuth()
                .then(() => setReady(true))
                .catch(() => setError(true));
            }}
            className="inline-flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-lg"
          >
            <RefreshCw className="w-4 h-4" /> Retry
          </button>
        </div>
      </div>
    );
  }

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex items-center gap-3 text-muted-foreground">
          <span className="w-5 h-5 border-2 border-current border-t-transparent rounded-full animate-spin" />
          Connecting...
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden bg-background">
      <Sidebar />
      <div className="flex-1 min-w-[560px] min-h-0 flex flex-col">
        <ChatPanel />
      </div>
      <RightPanel />
    </div>
  );
}
