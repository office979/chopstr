import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { isTerminalStatus } from "@/lib/pipeline";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const POLL_MS = 1500;
const MAX_LIFETIME_MS = 30 * 60 * 1000;

/* Server-Sent Events: streamt neue pipeline_events per Polling (1,5 s) und schließt bei ready/failed. */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) {
    return new Response("Projekt nicht gefunden", { status: 404 });
  }

  const encoder = new TextEncoder();
  const afterParam = Number(request.nextUrl.searchParams.get("after") ?? request.headers.get("last-event-id") ?? 0);
  let lastId = Number.isFinite(afterParam) ? afterParam : 0;
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const startedAt = Date.now();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: string, data: unknown, eventId?: number) => {
        if (closed) return;
        const lines = [
          eventId != null ? `id: ${eventId}` : null,
          `event: ${event}`,
          `data: ${JSON.stringify(data)}`,
          "",
          "",
        ].filter((l): l is string => l != null);
        controller.enqueue(encoder.encode(lines.join("\n")));
      };

      const finish = () => {
        if (closed) return;
        closed = true;
        if (timer) clearTimeout(timer);
        try {
          controller.close();
        } catch {
          /* bereits geschlossen */
        }
      };

      const tick = async () => {
        if (closed) return;
        try {
          const events = await repo.listPipelineEvents(id, lastId);
          for (const e of events) {
            lastId = Math.max(lastId, e.id);
            send("pipeline", e, e.id);
          }
          const current = await repo.getSource(id);
          if (current) {
            send("status", { status: current.status, status_message: current.status_message, updated_at: current.updated_at });
            if (isTerminalStatus(current.status)) {
              send("done", { status: current.status });
              finish();
              return;
            }
          }
        } catch (error) {
          send("error", { message: error instanceof Error ? error.message : "Unbekannter Fehler" });
        }
        if (Date.now() - startedAt > MAX_LIFETIME_MS) {
          finish();
          return;
        }
        timer = setTimeout(tick, POLL_MS);
      };

      send("hello", { source_id: id, poll_ms: POLL_MS });
      void tick();
      request.signal.addEventListener("abort", finish);
    },
    cancel() {
      closed = true;
      if (timer) clearTimeout(timer);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
