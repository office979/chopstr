import "server-only";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import type { Publication } from "@/lib/repo/types-api";
import { clipFormatHint, DEFAULT_TRACK_DAYS, linkCheckSummary, planLinkPublication, probeUrl, runLinkCheck, type LinkCheckDeps, type LinkCheckResult } from "./link-check";
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

export type RegisterLinkOutcome =
  | { ok: true; publication: Publication; check: LinkCheckResult; zusammenfassung: string[] }
  | { ok: false; status: 400 | 409; code: string; message: string; check: LinkCheckResult; duplicate_publication_id?: string };

/* Link am Clip eintragen: Linktest, dann Publikation mit status manual und tracking link. Der Worker misst
 * ab next_snapshot_at (local_worker.process_metrics). Gemeinsam für /api/v1/clips/{id}/links und die
 * Sitzungsroute der Oberfläche; die Gates (Zweck „eintragen“) prüft der Aufrufer. */
export async function registerLinkForClip(input: {
  clip: { id: string; platform: string; source_id: string };
  url: string;
  trackDays?: number;
  via: "api" | "ui";
  apiKeyId?: string;
}): Promise<RegisterLinkOutcome> {
  const check = await runLinkCheck(input.url, linkCheckDeps());
  const formatHint = clipFormatHint(check.platform, input.clip.platform);
  if (formatHint) check.hinweise.push(formatHint);
  const trackDays = input.trackDays ?? DEFAULT_TRACK_DAYS;
  const outcome = planLinkPublication(check, { now: Date.now(), trackDays });
  if (!outcome.ok) return { ...outcome, check };
  const { plan } = outcome;
  const publication = await getApiRepo().createLinkPublication({ clip_id: input.clip.id, ...plan, link_check: { ...plan.link_check } });
  await getRepo().audit({
    action: "publication.link_registered",
    entity: "publications",
    entity_id: publication.id,
    payload: {
      clip_id: input.clip.id,
      source_id: input.clip.source_id,
      platform: plan.platform,
      external_id: plan.external_id,
      tracking_until: plan.tracking_until,
      owned_by_connection: check.checks.owned_by_connection,
      via: input.via,
      ...(input.apiKeyId ? { api_key_id: input.apiKeyId } : {}),
    },
  });
  return { ok: true, publication, check, zusammenfassung: linkCheckSummary(check, plan.tracking_days) };
}
