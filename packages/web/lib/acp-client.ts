/**
 * ACP Client — streams events from /api/acp SSE bridge.
 *
 * Usage:
 *   const ctrl = new AbortController();
 *   for await (const evt of streamAgent("my query", ctrl.signal)) {
 *     if (evt.type === "text")  ...
 *     if (evt.type === "done")  break;
 *   }
 *   // To cancel early: ctrl.abort();
 */

// ── Event types ──

export type AcpEvent =
  | { type: "text"; text: string }
  | { type: "status"; text: string }
  | { type: "permission"; tool: string; approved: boolean }
  | { type: "log"; text: string }
  | { type: "error"; text: string }
  | { type: "done"; code?: number };

// ── Stream helper ──

export async function* streamAgent(
  message: string,
  conversationId?: string,
  signal?: AbortSignal,
): AsyncGenerator<AcpEvent> {
  // Get token from localStorage
  const token =
    typeof window !== "undefined" ? localStorage.getItem("arsenal_token") : null;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let resp: Response;
  try {
    resp = await fetch("/api/acp", {
      method: "POST",
      headers,
      body: JSON.stringify({ message, conversationId }),
      signal,
    });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      yield { type: "done" };
      return;
    }
    yield { type: "error", text: err instanceof Error ? err.message : "Network error" };
    yield { type: "done" };
    return;
  }

  if (!resp.ok) {
    const body = await resp.text().catch(() => "");
    yield { type: "error", text: `Agent request failed (${resp.status}): ${body}` };
    yield { type: "done" };
    return;
  }

  const reader = resp.body?.getReader();
  if (!reader) {
    yield { type: "error", text: "No response body" };
    yield { type: "done" };
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // SSE format: "data: {...}\n\n"
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        const trimmed = part.trim();
        if (!trimmed) continue;

        // Extract data payload
        for (const line of trimmed.split("\n")) {
          if (!line.startsWith("data: ")) continue;
          const json = line.slice(6);
          try {
            const evt = JSON.parse(json) as AcpEvent;
            yield evt;
          } catch {
            // Ignore unparseable lines
          }
        }
      }
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === "AbortError") {
      // User cancelled — clean exit
    } else {
      yield { type: "error", text: err instanceof Error ? err.message : "Stream error" };
    }
  } finally {
    reader.releaseLock();
  }

  yield { type: "done" };
}
