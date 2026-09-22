import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadClip } from "@/lib/api/lookup";
import { clipMedia, serializeClip } from "@/lib/api/serializers";
import { latestByClip } from "@/lib/guest/approval";

export const dynamic = "force-dynamic";

/* Clip mit Medien-URLs (media), aktueller Hook-Version, Captions und jüngster Gast-Freigabe */
export const GET = apiRoute<{ id: string }>("read", async (_request, { params }) => {
  const { clip, source } = await loadClip(params.id);
  const repo = getRepo();
  const [hook, captions, approvals] = await Promise.all([repo.getCurrentHook(clip.id), repo.getCurrentCaptions(clip.id), repo.listGuestApprovals(source.id)]);
  const guest = latestByClip(approvals).get(clip.id) ?? null;
  return apiJson({ clip: serializeClip(clip, { hook, captions, guest_approval: guest }), hook, media: clipMedia(clip) });
});
