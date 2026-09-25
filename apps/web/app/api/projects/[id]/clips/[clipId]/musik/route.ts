import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { getStore } from "@/lib/storage";
import { lesen, type MusikEingabe } from "@/lib/clips/musik";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string; clipId: string }> };

/* Welche Tonformate hereindürfen. Bewusst kurz: was ffmpeg im Renderlauf sicher liest, und
 * nichts, dessen Endung nur so aussieht. */
const ERLAUBT: Record<string, string> = {
  "audio/mpeg": "mp3",
  "audio/mp3": "mp3",
  "audio/wav": "wav",
  "audio/x-wav": "wav",
  "audio/mp4": "m4a",
  "audio/aac": "m4a",
  "audio/x-m4a": "m4a",
  "audio/ogg": "ogg",
  "audio/flac": "flac",
  "audio/x-flac": "flac",
};

/* 40 MB. Ein Musikstück von drei Minuten in 320 kbit/s sind gut sieben; wer mehr hochlädt, lädt
 * etwas anderes hoch. Die Grenze schützt die Ablage und den Renderlauf. */
const MAX_BYTES = 40 * 1024 * 1024;

/* PATCH: die Musik dieses Clips setzen oder entfernen.
 *
 * Body ist entweder die Angabe selbst oder `null` - „keine Musik" ist eine gültige Antwort und
 * braucht keinen eigenen Weg. */
export async function PATCH(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  let body: { musik?: unknown };
  try {
    body = (await request.json()) as { musik?: unknown };
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }

  const musik = body.musik == null ? null : lesen(body.musik as MusikEingabe);
  if (body.musik != null && musik == null) {
    return Response.json({ error: "Zu dieser Musik fehlt die Datei." }, { status: 400 });
  }
  const extras = await getPublishingRepo().updateClipExtras(clipId, { musik });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  await repo.audit({
    action: "clip.musik",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, quelle: musik?.quelle ?? null, name: musik?.name ?? null },
  });
  return Response.json({ ok: true, musik: extras.musik });
}

/* POST: eigene Musik hochladen.
 *
 * Die Datei landet unter `musik/<clip>/<zufall>.<endung>` im Ablagebereich der abgeleiteten
 * Dateien - dort, wo auch die fertigen Clips liegen, und damit im selben Löschlauf.
 *
 * Wer eigene Musik hochlädt, ist selbst dafür verantwortlich, die Rechte daran zu haben. Das ist
 * bei jedem Schnittprogramm so, und es steht auch in der Oberfläche.
 */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id, clipId } = await params;
  const repo = getRepo();
  const clip = await repo.getClip(clipId);
  if (!clip || clip.source_id !== id) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });

  const form = await request.formData().catch(() => null);
  const datei = form?.get("datei");
  if (!(datei instanceof File)) return Response.json({ error: "Keine Datei dabei." }, { status: 400 });

  const endung = ERLAUBT[datei.type];
  if (!endung) {
    return Response.json(
      { error: `${datei.type || "Dieses Format"} geht nicht. MP3, WAV, M4A, OGG oder FLAC.` },
      { status: 415 },
    );
  }
  if (datei.size > MAX_BYTES) {
    return Response.json(
      { error: `Die Datei ist ${(datei.size / 1024 / 1024).toFixed(0)} MB gross, mehr als 40 MB gehen nicht.` },
      { status: 413 },
    );
  }

  const key = `musik/${clipId}/${crypto.randomUUID()}.${endung}`;
  const bytes = new Uint8Array(await datei.arrayBuffer());
  await getStore().put("derived", key, bytes, datei.type);

  /* Der Name kommt aus dem Dateinamen, ohne Endung: „Franky Rizardo - Shinjuku.mp3" wird zu
   * „Franky Rizardo - Shinjuku". Er steht später im Dropdown, und eine Kennung aus 36 Zeichen
   * sagt dort niemandem etwas. */
  const name = datei.name.replace(/\.[^.]+$/, "").slice(0, 120) || "Eigene Musik";
  const musik = lesen({ quelle: "eigen", datei: key, name, ab_s: 0, lautstaerke_db: undefined, ducking: true });
  const extras = await getPublishingRepo().updateClipExtras(clipId, { musik });
  if (!extras) return Response.json({ error: "Clip nicht gefunden" }, { status: 404 });
  await repo.audit({
    action: "clip.musik",
    entity: "clips",
    entity_id: clipId,
    payload: { source_id: id, quelle: "eigen", name, bytes: datei.size },
  });
  return Response.json({ ok: true, musik: extras.musik }, { status: 201 });
}

export const runtime = "nodejs";
