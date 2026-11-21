import "server-only";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import type { Publication } from "@/lib/repo/types-api";
import { clipFormatHint, DEFAULT_TRACK_DAYS, DUPLICATE_MESSAGE, linkCheckSummary, planLinkPublication, probeOembed, publicationPlatformsFor, runLinkCheck, type LinkCheckDeps, type LinkCheckResult } from "./link-check";
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
    /* Lesend und über alle Plattformwerte, also auch OAuth-Publikationen mit derselben ID; gegen
     * gleichzeitige Anfragen sichert erst der eindeutige Index beim Einfügen ab */
    findDuplicate: async (platform, externalId) => {
      const p = await repo.findPublicationByExternal(publicationPlatformsFor(platform), externalId);
      return p ? { id: p.id } : null;
    },
    probe: (platform, url) => probeOembed(platform, url),
    now: Date.now,
  };
}

export type RegisterLinkOutcome =
  | { ok: true; publication: Publication; check: LinkCheckResult; zusammenfassung: string[] }
  | { ok: false; status: 400 | 409; code: string; message: string; check: LinkCheckResult; duplicate_publication_id?: string };

/* Link am Clip eintragen: Linktest, dann Publikation mit status manual und tracking link. Der Worker misst
 * ab next_snapshot_at (local_worker.process_metrics), aber nur, wenn der Link messbar ist. Gemeinsam für /api/v1/clips/{id}/links und die
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
  const created = await getApiRepo().createLinkPublication({
    clip_id: input.clip.id,
    connection_id: plan.connection_id,
    platform: plan.platform,
    external_id: plan.external_id,
    external_url: plan.external_url,
    published_at: plan.published_at,
    tracking_until: plan.tracking_until,
    next_snapshot_at: plan.next_snapshot_at,
    link_check: { ...plan.link_check, measurable: plan.measurable },
  });
  if (!created.created) {
    /* Gleichzeitige Anfrage war schneller: gleiche Antwort wie bei der lesenden Prüfung */
    check.checks.duplicate_publication_id = created.existing_id;
    if (!check.hinweise.includes(DUPLICATE_MESSAGE)) check.hinweise.push(DUPLICATE_MESSAGE);
    return { ok: false, status: 409, code: "link_duplicate", message: DUPLICATE_MESSAGE, check, ...(created.existing_id ? { duplicate_publication_id: created.existing_id } : {}) };
  }
  const { publication } = created;
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
  return { ok: true, publication, check, zusammenfassung: linkCheckSummary(check, plan) };
}
