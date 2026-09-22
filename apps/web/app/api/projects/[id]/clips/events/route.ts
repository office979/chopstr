import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";
import type { Clip } from "@/lib/repo/types";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const POLL_MS = 1500;
const MAX_LIFETIME_MS = 30 * 60 * 1000;

function isSettled(c: Clip): boolean {
  return c.status === "rendered" || c.status === "failed" || c.status === "exported";
}

function signature(clips: Clip[]): string {
  return clips.map((c) => `${c.id}:${c.status}:${c.updated_at}`).join("|");
}

/* Server-Sent Events für Renders: pollt pipeline_events mit step = 'render' alle 1,5 s und sendet bei
 * Änderungen den Clip-Stand. Schließt, wenn alle Clips gerendert, exportiert oder fehlgeschlagen sind. */
export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const source = await repo.getSource(id);
  if (!source) {
    return new Response("Projekt nicht gefunden", { status: 404 });
  }

  const encoder = new TextEncoder();
  const afterParam = Number(request.nextUrl.searchParams.get("after") ?? request.headers.get("last-event-id") ?? 0);
  let lastId = Number.isFinite(afterParam) ? afterParam : 0;
  let lastSignature = "";
  let closed = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const startedAt = Date.now();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (event: string, data: unknown, eventId?: number) => {
        if (closed) return;
        const lines = [eventId != null ? `id: ${eventId}` : null, `event: ${event}`, `data: ${JSON.stringify(data)}`, "", ""].filter(
          (l): l is string => l != null,
        );
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
          const all = await repo.listPipelineEvents(id, lastId);
          for (const e of all) {
            lastId = Math.max(lastId, e.id);
            if (e.step === "render") send("render", e, e.id);
          }
          const clips = await repo.listClips(id);
          const sig = signature(clips);
          if (sig !== lastSignature) {
            lastSignature = sig;
            send("clips", { clips });
          }
          if (clips.length > 0 && clips.every(isSettled)) {
            send("done", { rendered: clips.filter((c) => c.status === "rendered").length, total: clips.length });
            finish();
            return;
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
