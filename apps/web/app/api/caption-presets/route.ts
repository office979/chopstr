import type { NextRequest } from "next/server";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";
import { stilPruefen } from "@/lib/clips/caption-style";

export const dynamic = "force-dynamic";

const NAME_MAX = 60;

/* GET: Untertitel-Vorlagen des Workspace. */
export async function GET() {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  return Response.json({ presets: await getPublishingRepo().listCaptionPresets() });
}

/* POST: Vorlage anlegen oder unter gleichem Namen aktualisieren. Body: { name, style }. */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  let body: { name?: unknown; style?: unknown };
  try {
    body = (await request.json()) as typeof body;
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const name = String(body.name ?? "").trim();
  if (!name) return Response.json({ error: "Die Vorlage braucht einen Namen" }, { status: 400 });
  if (name.length > NAME_MAX) return Response.json({ error: `Der Name darf höchstens ${NAME_MAX} Zeichen haben` }, { status: 400 });
  const preset = await getPublishingRepo().saveCaptionPreset(name, stilPruefen(body.style));
  return Response.json({ ok: true, preset });
}
