import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireApiRole } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* DELETE: Vorlage entfernen. Clips, die den Stil schon übernommen haben, behalten ihn:
 * beim Übernehmen werden die Werte in den Clip geschrieben, nicht verlinkt. */
export async function DELETE(_request: Request, { params }: Params) {
  const auth = await requireApiRole("clip.render");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const weg = await getPublishingRepo().deleteCaptionPreset(id);
  if (!weg) return Response.json({ error: "Vorlage nicht gefunden" }, { status: 404 });
  return Response.json({ ok: true });
}
