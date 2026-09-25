import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiSession } from "@/lib/auth/guard";
import { mediaUrl } from "@/lib/clips/labels";
import { loadClipContext } from "@/lib/publishing/clip-context";
import { ausgabeSatz } from "@/lib/clips/ausgabe";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

const KINDS = { mp4: "file_key", srt: "srt_key", vtt: "vtt_key", poster: "poster_key" } as const;

/* GET ?kind=mp4|srt|vtt|poster: der Weg nach draussen.
 *
 * Hier stand bis zuletzt genau eine Prüfung: wartet noch eine Gastfreigabe? Alles andere fehlte.
 * Ein Clip mit einem Schnitt, der eine Verneinung wegschneidet, ein noch laufender Lauf,
 * ein fehlgeschlagener Lauf: alles herunterladbar, sobald man die Adresse kannte. Die Oberfläche
 * sperrte den Knopf, aber ein gesperrter Knopf ist keine Sperre, sondern eine Bitte.
 *
 * Jetzt entscheidet lib/clips/ausgabe.ts, dieselbe Rechnung wie für das Veröffentlichen und
 * dieselbe, die der Knopf anzeigt. Untertiteldateien folgen derselben Entscheidung wie das Video:
 * eine SRT zu einem Schnitt, der etwas anderes sagt als der Sprecher, ist genauso falsch.
 */
export async function GET(request: NextRequest, { params }: Params) {
  const auth = await requireApiSession();
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const kind = request.nextUrl.searchParams.get("kind") ?? "mp4";
  if (!(kind in KINDS)) return Response.json({ error: "kind muss mp4, srt, vtt oder poster sein" }, { status: 400 });
  const ctx = await loadClipContext(id, clipId);
  if (!ctx) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  /* Das Vorschaubild ist kein Export: es steht in der Liste und im Player und sagt nichts darüber
   * aus, was hinausgeht. Es zu sperren würde die Seite leer machen, ohne irgendetwas zu schützen. */
  if (kind !== "poster" && !ctx.herunterladen.erlaubt) {
    const grund = ctx.herunterladen.gruende[0];
    return Response.json(
      { error: ausgabeSatz(grund), code: grund.code, gruende: ctx.herunterladen.gruende },
      { status: 409 },
    );
  }

  const clip = ctx.clip;
  const key = clip[KINDS[kind as keyof typeof KINDS]];
  const url = mediaUrl(process.env.NEXT_PUBLIC_MEDIA_BASE_URL, key);
  if (!url) return Response.json({ error: "Datei noch nicht verfügbar" }, { status: 404 });

  const repo = getRepo();
  if (kind === "mp4" && clip.status === "rendered") {
    await repo.updateClip(clip.id, { status: "exported" });
    await repo.audit({ action: "export.created", entity: "clips", entity_id: clip.id, payload: { source_id: id, kind, key } });
  }
  /* Lokaler Modus: NEXT_PUBLIC_MEDIA_BASE_URL ist relativ (/api/media), Response.redirect braucht eine absolute URL */
  return Response.redirect(new URL(url, request.nextUrl.origin), 302);
}
