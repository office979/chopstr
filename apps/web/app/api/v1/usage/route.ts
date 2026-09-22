import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { serializeUsage } from "@/lib/api/serializers";
import { getQuota } from "@/lib/billing/quota";
import { noteUsageThresholds } from "@/lib/outbox";

export const dynamic = "force-dynamic";

/* Kontingent des laufenden Monats; prüft nebenbei die 80-/100-%-Schwellen (usage.threshold) */
export const GET = apiRoute("read", async (_request, { auth }) => {
  const quota = await getQuota(getRepo());
  void noteUsageThresholds(auth.workspaceId, quota);
  return apiJson({ usage: serializeUsage(quota) });
});
