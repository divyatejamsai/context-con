import type { RunEvent } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

// When set, live runs go through the Countersign agent endpoint: passport check, ledger entries and Send Guard.
export const AGENT_ID = process.env.NEXT_PUBLIC_AGENT_ID || "";

export type RunMode = "replay" | "live";

export const liveUrl = () => (AGENT_ID ? `${API_URL}/api/agents/${encodeURIComponent(AGENT_ID)}/run` : `${API_URL}/api/run`);

/**
 * POSTs the brief and yields parsed events. Works for both real SSE ("data: {...}\n\n")
 * and plain NDJSON lines, so it tolerates whatever the backend ends up emitting.
 */
export async function* streamRun(brief: string, mode: RunMode, signal: AbortSignal): AsyncGenerator<RunEvent> {
  const url = mode === "live" ? liveUrl() : "/api/replay";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify({ brief }),
    signal,
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(`Backend returned ${res.status}${text ? `: ${text.slice(0, 200)}` : ""}`);
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  let dataLines: string[] = [];

  const flush = function* (): Generator<RunEvent> {
    if (!dataLines.length) return;
    const ev = parse(dataLines.join("\n"));
    dataLines = [];
    if (ev) yield ev;
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).replace(/\r$/, "");
      buffer = buffer.slice(nl + 1);
      if (line === "") {
        yield* flush();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).trimStart());
      } else if (line.startsWith(":") || /^(event|id|retry):/.test(line)) {
        // SSE comment / metadata, ignore
      } else {
        // NDJSON fallback
        yield* flush();
        const ev = parse(line);
        if (ev) yield ev;
      }
    }
  }
  if (buffer.trim()) dataLines.push(buffer.replace(/^data:\s?/, ""));
  yield* flush();
}

function parse(raw: string): RunEvent | null {
  try {
    const obj = JSON.parse(raw);
    return obj && typeof obj.type === "string" ? (obj as RunEvent) : null;
  } catch {
    return null;
  }
}
