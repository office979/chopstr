import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { loadClip } from "@/lib/api/lookup";
import { serializePublication } from "@/lib/api/serializers";
import { buildClipPerformance } from "@/lib/publishing/performance";

export const dynamic = "force-dynamic";

/* Alle Publikationen eines Clips mit ihren neuesten Zahlen, dazu das Hook-Muster der aktuellen Hook-Version.
 * Die interne Hook-Bewertung steht hier bewusst nicht: sie ist eine redaktionelle Einschätzung und keine
 * Vorhersage der Performance. */
export const GET = apiRoute<{ id: string }>("read", async (_request, { params }) => {
  const { clip } = await loadClip(params.id);
  const repo = getApiRepo();
  const [publications, hook] = await Promise.all([repo.listPublicationsForClip(clip.id), getRepo().getCurrentHook(clip.id)]);
  const ids = publications.map((p) => p.id);
  const [snapshots, feedback] = await Promise.all([repo.listMetricSnapshots(ids), repo.listWindowFeedback(ids)]);
  return apiJson({
    clip_id: clip.id,
    platform: clip.platform,
    hook: hook ? { pattern: hook.pattern, onscreen_hook: hook.onscreen_hook, version: hook.version } : null,
    ...buildClipPerformance(publications.map((p) => serializePublication(p)), snapshots, feedback),
  });
});
