/**
 * AI Chat route — Vercel AI SDK + MCP
 *
 * Connects to the git-arsenal MCP server (stdio) to expose search_repos
 * and get_repo_detail tools, then streams the LLM response back via the
 * AI SDK data-stream protocol.
 */
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { createMCPClient } from "@ai-sdk/mcp";
import { Experimental_StdioMCPTransport } from "@ai-sdk/mcp/mcp-stdio";
import { streamText, stepCountIs, convertToModelMessages } from "ai";
import { resolve } from "path";
import { SEARCH_MODE_SYSTEM_PROMPT } from "@/lib/prompts";

const LLM_BASE_URL =
  process.env.LLM_BASE_URL || "https://open.bigmodel.cn/api/paas/v4";
const LLM_API_KEY = process.env.LLM_API_KEY || "";
const LLM_MODEL = process.env.LLM_MODEL || "glm-4.7";

const ARSENAL_API_URL =
  process.env.ARSENAL_API_URL || "http://localhost:8003";
const GIT_ARSENAL_ROOT =
  process.env.GIT_ARSENAL_ROOT || resolve(process.cwd(), "../..");

const provider = createOpenAICompatible({
  name: "zhipu",
  baseURL: LLM_BASE_URL,
  apiKey: LLM_API_KEY,
});

export async function POST(req: Request) {
  const { messages: uiMessages } = await req.json();

  const modelMessages = await convertToModelMessages(uiMessages);

  const mcpServerPath = resolve(
    GIT_ARSENAL_ROOT,
    "packages/mcp-server/index.js",
  );

  const transport = new Experimental_StdioMCPTransport({
    command: "node",
    args: [mcpServerPath],
    env: {
      ...process.env as Record<string, string>,
      ARSENAL_API_URL,
    },
  });

  const mcpClient = await createMCPClient({ transport });

  try {
    const tools = await mcpClient.tools();

    const result = streamText({
      model: provider(LLM_MODEL),
      system: SEARCH_MODE_SYSTEM_PROMPT,
      messages: modelMessages,
      tools,
      stopWhen: stepCountIs(3),
      onFinish: async ({ steps, text }) => {
        console.log(`[chat] done: ${steps.length} steps, ${text.length} chars`);
        await mcpClient.close();
      },
      onError: async (error) => {
        console.error("[chat] stream error:", error);
        await mcpClient.close();
      },
      onStepFinish: ({ stepType, toolCalls }) => {
        if (toolCalls?.length) {
          console.log(`[chat] step ${stepType}: tools=[${toolCalls.map(t => t.toolName).join(",")}]`);
        }
      },
    });

    return result.toUIMessageStreamResponse();
  } catch (error) {
    console.error("[chat] route error:", error);
    await mcpClient.close();
    const msg = error instanceof Error ? error.message : "Internal error";
    return new Response(JSON.stringify({ error: msg }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
}
