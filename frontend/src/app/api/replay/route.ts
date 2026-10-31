import { readFile } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

// Streams fixtures/run.jsonl as SSE with realistic pacing, so the UI can be demoed with no backend.
async function loadEvents(): Promise<string[]> {
  const candidates = [
    process.env.FIXTURE_PATH,
    path.join(process.cwd(), "fixtures", "run.jsonl"),
    path.join(process.cwd(), "..", "fixtures", "run.jsonl"),
  ].filter(Boolean) as string[];
  for (const p of candidates) {
    try {
      const text = await readFile(p, "utf8");
      return text.split("\n").map((l) => l.trim()).filter(Boolean);
    } catch {}
  }
  return [JSON.stringify({ type: "error", step: "replay", message: "No fixtures/run.jsonl found" })];
}

function delayFor(line: string, speed: number): number {
  const type = /"type"\s*:\s*"(\w+)"/.exec(line)?.[1];
  const base = type === "candidate" ? 500 : type === "done" ? 300 : 900;
  return base / speed;
}

async function handle(req: Request) {
  const speed = Number(new URL(req.url).searchParams.get("speed")) || 1;
  const lines = await loadEvents();
  const encoder = new TextEncoder();
  const stream = new ReadableStream({
    async start(controller) {
      for (const line of lines) {
        if (req.signal.aborted) break;
        await new Promise((r) => setTimeout(r, delayFor(line, speed)));
        controller.enqueue(encoder.encode(`data: ${line}\n\n`));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache, no-transform", Connection: "keep-alive" },
  });
}

export const GET = handle;
export const POST = handle;
