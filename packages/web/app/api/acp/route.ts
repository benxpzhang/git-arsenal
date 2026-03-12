/**
 * ACP Bridge — persistent process pool
 *
 * Architecture:
 *   - Each conversation maps to one Kode-Agent child process
 *   - The process stays alive between messages for multi-turn context
 *   - session/prompt is called for each new message (Kode-Agent keeps message history)
 *   - Idle processes are cleaned up after IDLE_TIMEOUT_MS
 *
 * Protocol flow (first message):
 *   1. initialize    → handshake
 *   2. session/new   → create session (cwd + mcpServers), returns sessionId
 *   3. session/prompt → send user prompt, streams session/update notifications
 *
 * Protocol flow (subsequent messages):
 *   3. session/prompt → send prompt to existing session (includes prior context)
 */
import { NextRequest } from "next/server";
import { spawn, type ChildProcess } from "child_process";
import * as readline from "readline";
import { resolve } from "path";

// ── Config ──

const KODE_PATH = process.env.KODE_ACP_PATH || "";
const GIT_ARSENAL_ROOT = process.env.GIT_ARSENAL_ROOT || "";
const ARSENAL_API_URL = process.env.ARSENAL_API_URL || "http://localhost:8003";

const MAX_CONCURRENT = parseInt(process.env.ACP_MAX_CONCURRENT || "5", 10);

/** Per-prompt timeout in ms (default 300s — generous for multi-tool agent) */
const PROMPT_TIMEOUT_MS = parseInt(process.env.ACP_PROMPT_TIMEOUT_MS || "300000", 10);

/** Idle timeout: kill process if no prompt for this long (default 5 min) */
const IDLE_TIMEOUT_MS = parseInt(process.env.ACP_IDLE_TIMEOUT_MS || "300000", 10);

const ALLOWED_TOOL_PREFIX = "mcp__git-arsenal__";

// ── Persistent Agent Session ──

interface AgentSession {
  child: ChildProcess;
  sessionId: string;
  conversationId: string;
  rpcId: number;
  pendingRpc: Map<number, { resolve: (v: unknown) => void; reject: (e: Error) => void }>;
  /** All line listeners — each active prompt subscribes here */
  lineListeners: Set<(line: string) => void>;
  rl: readline.Interface;
  errRl: readline.Interface | null;
  lastUsed: number;
  ready: boolean;
  dead: boolean;
  idleTimer: ReturnType<typeof setTimeout> | null;
}

// Global pool (survives hot reloads in dev via globalThis)
const _g = globalThis as unknown as {
  __acpPool: Map<string, AgentSession>;
  __acpPoolInit: boolean;
};
if (!_g.__acpPoolInit) {
  _g.__acpPool = new Map();
  _g.__acpPoolInit = true;
}
const pool: Map<string, AgentSession> = _g.__acpPool;

function getActiveCount() {
  return pool.size;
}

// ── Build MCP Servers config ──

function buildMcpServersConfig(token: string): Record<string, unknown>[] {
  const mcpServerPath = resolve(GIT_ARSENAL_ROOT || ".", "packages/mcp-server/index.js");
  return [
    {
      name: "git-arsenal",
      type: "stdio",
      command: "node",
      args: [mcpServerPath],
      env: [
        { name: "ARSENAL_API_URL", value: ARSENAL_API_URL },
        ...(token ? [{ name: "ARSENAL_TOKEN", value: token }] : []),
      ],
    },
  ];
}

// ── Session lifecycle ──

function resetIdleTimer(session: AgentSession) {
  if (session.idleTimer) clearTimeout(session.idleTimer);
  session.idleTimer = setTimeout(() => {
    console.error(`[ACP] Idle timeout for conversation ${session.conversationId}, cleaning up`);
    destroySession(session.conversationId);
  }, IDLE_TIMEOUT_MS);
}

function destroySession(conversationId: string) {
  const session = pool.get(conversationId);
  if (!session) return;

  session.dead = true;
  pool.delete(conversationId);

  if (session.idleTimer) clearTimeout(session.idleTimer);

  if (session.child && !session.child.killed) {
    try {
      session.child.kill("SIGTERM");
      setTimeout(() => {
        if (session.child && !session.child.killed) {
          try { session.child.kill("SIGKILL"); } catch { /* ignore */ }
        }
      }, 3000);
    } catch { /* ignore */ }
  }

  console.error(`[ACP] Session destroyed: ${conversationId}, remaining: ${pool.size}`);
}

async function getOrCreateSession(
  conversationId: string,
  token: string,
): Promise<AgentSession> {
  const existing = pool.get(conversationId);
  if (existing && !existing.dead) {
    existing.lastUsed = Date.now();
    resetIdleTimer(existing);
    return existing;
  }

  // ── Spawn new process ──
  const child = spawn("node", [KODE_PATH, "--acp"], {
    cwd: GIT_ARSENAL_ROOT || undefined,
    env: {
      ...process.env,
      ARSENAL_TOKEN: token,
      ARSENAL_API_URL,
    },
    stdio: ["pipe", "pipe", "pipe"],
  });

  const session: AgentSession = {
    child,
    sessionId: "",
    conversationId,
    rpcId: 1,
    pendingRpc: new Map(),
    lineListeners: new Set(),
    rl: readline.createInterface({ input: child.stdout! }),
    errRl: child.stderr ? readline.createInterface({ input: child.stderr! }) : null,
    lastUsed: Date.now(),
    ready: false,
    dead: false,
    idleTimer: null,
  };

  // ── Route stdout lines to pendingRpc + lineListeners ──
  session.rl.on("line", (line: string) => {
    // First try to match pending RPC responses
    try {
      const msg = JSON.parse(line);
      const hasId = typeof msg.id === "number" || typeof msg.id === "string";
      const isResponse = hasId && !msg.method && ("result" in msg || "error" in msg);

      if (isResponse) {
        const pending = session.pendingRpc.get(Number(msg.id));
        if (pending) {
          session.pendingRpc.delete(Number(msg.id));
          if ("error" in msg && msg.error) {
            pending.reject(new Error(msg.error.message || "RPC error"));
          } else {
            pending.resolve(msg.result);
          }
          return; // Don't forward RPC responses to line listeners
        }
      }
    } catch {
      // Not JSON — fall through to listeners
    }

    // Forward to all active line listeners (current prompt's SSE handler)
    for (const listener of session.lineListeners) {
      listener(line);
    }
  });

  // Process exit — mark dead, cleanup
  child.on("close", (code) => {
    console.error(`[ACP] Child exited code=${code} for conversation=${conversationId}`);
    session.dead = true;
    pool.delete(conversationId);
    if (session.idleTimer) clearTimeout(session.idleTimer);
  });

  child.on("error", (err) => {
    console.error(`[ACP] Child error for conversation=${conversationId}: ${err.message}`);
    session.dead = true;
    pool.delete(conversationId);
  });

  // ── ACP Handshake ──
  function sendRpc(method: string, params: Record<string, unknown>): Promise<unknown> {
    return new Promise((resolveRpc, rejectRpc) => {
      if (session.dead || !child.stdin || child.killed) {
        rejectRpc(new Error("Child process not available"));
        return;
      }
      const id = session.rpcId++;
      session.pendingRpc.set(id, { resolve: resolveRpc, reject: rejectRpc });
      child.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");

      // Timeout for handshake RPCs
      setTimeout(() => {
        if (session.pendingRpc.has(id)) {
          session.pendingRpc.delete(id);
          rejectRpc(new Error(`RPC ${method} timed out`));
        }
      }, 30000);
    });
  }

  // Step 1: Initialize
  await sendRpc("initialize", {
    protocolVersion: 1,
    clientCapabilities: {},
    clientInfo: { name: "git-arsenal-web", version: "1.0.0" },
  });

  // Step 2: Create session
  const absoluteCwd = resolve(GIT_ARSENAL_ROOT);
  const mcpServers = buildMcpServersConfig(token);
  const sessionResult = (await sendRpc("session/new", {
    cwd: absoluteCwd,
    mcpServers,
  })) as { sessionId?: string };

  if (!sessionResult?.sessionId) {
    child.kill("SIGTERM");
    throw new Error("Failed to create agent session");
  }

  session.sessionId = sessionResult.sessionId;
  session.ready = true;

  pool.set(conversationId, session);
  resetIdleTimer(session);

  console.error(`[ACP] New session: conv=${conversationId} session=${session.sessionId} pool=${pool.size}`);
  return session;
}

// ── POST handler ──

export async function POST(req: NextRequest) {
  if (!KODE_PATH) {
    return new Response(JSON.stringify({ error: "KODE_ACP_PATH not configured" }), {
      status: 500, headers: { "Content-Type": "application/json" },
    });
  }
  if (!GIT_ARSENAL_ROOT) {
    return new Response(JSON.stringify({ error: "GIT_ARSENAL_ROOT not configured" }), {
      status: 500, headers: { "Content-Type": "application/json" },
    });
  }
  if (getActiveCount() >= MAX_CONCURRENT) {
    return new Response(JSON.stringify({
      error: "Too many concurrent sessions. Please try again shortly.",
      active: getActiveCount(), limit: MAX_CONCURRENT,
    }), { status: 503, headers: { "Content-Type": "application/json" } });
  }

  const body = await req.json();
  const userMessage: string = body.message || "";
  const conversationId: string = body.conversationId || `anon-${Date.now()}`;

  const authHeader = req.headers.get("Authorization") || "";
  const token = authHeader.replace("Bearer ", "");

  // ── Get or create persistent session ──
  let session: AgentSession;
  let isNewSession = false;
  try {
    isNewSession = !pool.has(conversationId);
    session = await getOrCreateSession(conversationId, token);
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : "Failed to create agent session";
    return new Response(JSON.stringify({ error: msg }), {
      status: 500, headers: { "Content-Type": "application/json" },
    });
  }

  // ── SSE stream for this prompt ──
  let promptDone = false;
  let promptTimer: ReturnType<typeof setTimeout> | null = null;

  const stream = new ReadableStream({
    start(controller) {
      function sse(data: Record<string, unknown>) {
        try {
          controller.enqueue(`data: ${JSON.stringify(data)}\n\n`);
        } catch { /* controller closed */ }
      }

      if (isNewSession) {
        sse({ type: "status", text: "Agent initialized, sending prompt..." });
      }

      // ── Line listener for this prompt ──
      const lineHandler = (line: string) => {
        try {
          const msg = JSON.parse(line);

          // ── session/request_permission ──
          if (msg.method === "session/request_permission") {
            const toolCall = msg.params?.toolCall || {};
            const toolTitle = toolCall.title || "";
            const toolCallId = toolCall.toolCallId || "";

            const approved =
              typeof toolTitle === "string" &&
              (toolTitle.startsWith(ALLOWED_TOOL_PREFIX) ||
                toolTitle.includes("git-arsenal") ||
                toolTitle.includes("search_repos") ||
                toolTitle.includes("get_repo_detail"));

            // Respond to permission request
            if (session.child?.stdin && !session.child.killed) {
              session.child.stdin.write(
                JSON.stringify({
                  jsonrpc: "2.0",
                  id: msg.id,
                  result: {
                    outcome: approved
                      ? { outcome: "selected", optionId: "allow_once" }
                      : { outcome: "selected", optionId: "reject_once" },
                  },
                }) + "\n",
              );
            }

            sse({ type: "permission", tool: toolTitle || toolCallId, approved });
            return;
          }

          // ── session/update ──
          if (msg.method === "session/update") {
            const update = msg.params?.update;
            if (!update) return;

            const kind = update.sessionUpdate;

            if (kind === "agent_message_chunk") {
              const text = update.content?.text || "";
              // Filter out Kode-Agent internal interruption messages
              if (text && !text.includes("[Request interrupted by user for tool use]")) {
                sse({ type: "text", text });
              }
              return;
            }

            if (kind === "agent_thought_chunk") {
              const text = update.content?.text || "";
              if (text) sse({ type: "status", text: `💭 ${text.slice(0, 200)}` });
              return;
            }

            if (kind === "tool_call") {
              sse({ type: "status", text: `🔧 ${update.title || "tool"} (${update.status || "pending"})` });
              return;
            }

            if (kind === "tool_call_update") {
              if (update.status === "in_progress") {
                sse({ type: "status", text: "⏳ Tool running..." });
              } else if (update.status === "completed" || update.status === "done") {
                sse({ type: "status", text: "✅ Tool done" });
              }
              if (Array.isArray(update.content)) {
                for (const c of update.content) {
                  if (c?.content?.type === "text" && c.content.text) {
                    sse({ type: "log", text: c.content.text });
                  }
                }
              }
              return;
            }

            // Skip informational updates
            if (kind === "available_commands" || kind === "current_mode" ||
                kind === "available_commands_update" || kind === "current_mode_update") {
              return;
            }

            sse({ type: "log", text: `[update] ${kind}` });
            return;
          }

          // Other methods — log
          if (msg.method) {
            sse({ type: "log", text: `[${msg.method}]` });
            return;
          }
        } catch {
          // Not JSON — ignore
        }
      };

      // Subscribe to session's output
      session.lineListeners.add(lineHandler);

      // Stderr forwarding (only from this prompt onward)
      const stderrHandler = (line: string) => {
        if (line.trim()) {
          sse({ type: "log", text: `[stderr] ${line}` });
        }
      };
      session.errRl?.on("line", stderrHandler);

      // ── Send session/prompt and WAIT for response ──
      const promptId = session.rpcId++;
      const promptMsg = JSON.stringify({
        jsonrpc: "2.0",
        id: promptId,
        method: "session/prompt",
        params: {
          sessionId: session.sessionId,
          prompt: [{ type: "text", text: userMessage }],
        },
      });

      session.pendingRpc.set(promptId, {
        resolve: (result: unknown) => {
          promptDone = true;
          if (promptTimer) clearTimeout(promptTimer);

          const stopReason = (result as Record<string, unknown>)?.stopReason || "end_turn";
          sse({ type: "done", stopReason });

          // Unsubscribe
          session.lineListeners.delete(lineHandler);
          session.errRl?.removeListener("line", stderrHandler);

          try { controller.close(); } catch { /* already closed */ }
        },
        reject: (err: Error) => {
          promptDone = true;
          if (promptTimer) clearTimeout(promptTimer);

          sse({ type: "error", text: err.message });
          sse({ type: "done", stopReason: "error" });

          session.lineListeners.delete(lineHandler);
          session.errRl?.removeListener("line", stderrHandler);

          try { controller.close(); } catch { /* already closed */ }
        },
      });

      session.child.stdin!.write(promptMsg + "\n");

      // Per-prompt timeout
      promptTimer = setTimeout(() => {
        if (!promptDone) {
          session.pendingRpc.delete(promptId);
          sse({ type: "error", text: "Prompt timed out" });
          sse({ type: "done", stopReason: "timeout" });

          session.lineListeners.delete(lineHandler);
          session.errRl?.removeListener("line", stderrHandler);

          try { controller.close(); } catch { /* already closed */ }
        }
      }, PROMPT_TIMEOUT_MS);

      // If process dies mid-prompt
      const closeHandler = () => {
        if (!promptDone) {
          promptDone = true;
          if (promptTimer) clearTimeout(promptTimer);

          sse({ type: "error", text: "Agent process exited unexpectedly" });
          sse({ type: "done", stopReason: "process_exit" });

          session.lineListeners.delete(lineHandler);
          try { controller.close(); } catch { /* already closed */ }
        }
      };
      session.child.once("close", closeHandler);
    },

    cancel() {
      // Client disconnected — don't kill the process, just stop streaming
      console.error(`[ACP] Client disconnected for conv=${conversationId}`);
      // We could optionally send session/cancel here
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}

// ── GET: health/status ──

export async function GET() {
  const sessions: Record<string, unknown>[] = [];
  for (const [convId, s] of pool) {
    sessions.push({
      conversationId: convId,
      sessionId: s.sessionId,
      ready: s.ready,
      dead: s.dead,
      age: Math.round((Date.now() - s.lastUsed) / 1000) + "s idle",
      listeners: s.lineListeners.size,
    });
  }
  return new Response(
    JSON.stringify({ active: pool.size, limit: MAX_CONCURRENT, idleTimeoutMs: IDLE_TIMEOUT_MS, sessions }),
    { headers: { "Content-Type": "application/json" } },
  );
}

// ── DELETE: force-kill a session (for debugging) ──

export async function DELETE(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const convId = searchParams.get("conversationId");
  if (convId && pool.has(convId)) {
    destroySession(convId);
    return new Response(JSON.stringify({ ok: true }), { headers: { "Content-Type": "application/json" } });
  }
  return new Response(JSON.stringify({ error: "Session not found" }), {
    status: 404, headers: { "Content-Type": "application/json" },
  });
}
