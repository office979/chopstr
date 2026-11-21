import "server-only";
import { getApiRepo } from "@/lib/repo/api";
import { probeUrl, type LinkCheckDeps } from "./link-check";
import { resolvePostUrl } from "./links";
import { readPublicMetrics } from "./public-metrics";

/* Echte Abhängigkeiten des Linktests: Netz über fetch, Daten über das API-Repository im Sitzungskontext.
 * Getrennt von link-check.ts, damit die Logik ohne server-only und ohne Datenbank testbar bleibt. */
export function linkCheckDeps(): LinkCheckDeps {
  const repo = getApiRepo();
  return {
    resolve: (url) => resolvePostUrl(url),
    readPublic: (platform, externalId) => readPublicMetrics(platform, externalId),
    listConnections: async () =>
      (await repo.listPlatformConnections()).map((c) => ({
        id: c.id,
        platform: c.platform,
        account_label: c.account_label,
        external_account_id: c.external_account_id ?? null,
        status: c.status,
      })),
    findDuplicate: async (platform, externalId) => {
      const p = await repo.findPublicationByExternal(platform, externalId);
      return p ? { id: p.id } : null;
    },
    probe: (url) => probeUrl(url),
    now: Date.now,
  };
}
