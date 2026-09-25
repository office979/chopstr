import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { getStore } from "@/lib/storage";
import { lesen } from "@/lib/clips/musik";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* GET: die Musikdatei dieses Clips.
 *
 * Wozu eine eigene Route, wenn die Datei schon in der Ablage liegt? Weil der Ablageschlüssel
 * nicht in den Browser gehört: er ist der Weg zu allen abgeleiteten Dateien dieses Teams. Hier
 * kommt man nur an die Musik DIESES Clips, und nur mit einer gültigen Sitzung.
 *
 * Die Oberfläche braucht sie, um die LÄNGE des Stücks zu kennen: ohne sie lässt sich nicht sagen,
 * wie weit die Musikspur geschoben werden darf.
 */
export async function GET(_request: Request, { params }: Params) {
  const auth = await requireApiRole("source.read");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const clip = await getRepo().getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  const extras = (await getPublishingRepo().getClipExtras([clipId]))[0];
  const musik = lesen(extras?.musik);
  if (!musik || musik.quelle !== "eigen") return Response.json({ error: "Keine eigene Musik" }, { status: 404 });

  const datei = await getStore().get("derived", musik.datei);
  if (!datei) return Response.json({ error: "Die Musikdatei ist nicht mehr da" }, { status: 404 });

  return new Response(new Uint8Array(datei.body), {
    headers: {
      "Content-Type": datei.contentType ?? "audio/mpeg",
      "Content-Length": String(datei.body.byteLength),
      /* Privat: die Datei gehört einem Team, nicht dem Netz. */
      "Cache-Control": "private, max-age=3600",
    },
  });
}
