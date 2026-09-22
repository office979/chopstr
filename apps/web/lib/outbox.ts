import "server-only";
import { isDemoMode } from "@/lib/env";
import { getApiRepo } from "@/lib/repo/api";
import type { QuotaState } from "@/lib/billing/quota";
import { WEBHOOK_EVENTS, WEBHOOK_PING_EVENT, type OutboxEvent } from "@/lib/repo/types-api";

/* Web-seitige Outbox (PHASE5.md, 5a): Statuswechsel der Web-App landen als Zeile in outbox_events, der
 * OutboxWorkflow des Workers verteilt sie an Webhook-Endpunkte. Payloads enthalten nur IDs, Titel, Status,
 * Zähler und URLs, nie Transkripte oder Hook-Texte. Spiegel von workers/chopstr_worker/outbox.py. */

export const OUTBOX_EVENTS: readonly string[] = [...WEBHOOK_EVENTS, WEBHOOK_PING_EVENT];

export async function emitOutbox(
  workspaceId: string,
  event: string,
  entity: string | null,
  entityId: string | null,
  payload: Record<string, unknown> = {},
  options: { processed?: boolean } = {},
): Promise<OutboxEvent | null> {
  if (!OUTBOX_EVENTS.includes(event)) throw new Error(`Unbekanntes Outbox-Ereignis: ${event}`);
  if (isDemoMode()) console.info(`[outbox] Demo: ${event} ${entity ?? ""} ${entityId ?? ""} nur im Speicher`);
  try {
    return await getApiRepo().insertOutboxEvent({
      workspace_id: workspaceId,
      event,
      entity,
      entity_id: entityId,
      payload,
      processed_at: options.processed ? new Date().toISOString() : null,
    });
  } catch (error) {
    /* Ein Webhook darf nie die eigentliche Aktion scheitern lassen */
    console.warn(`[outbox] ${event} konnte nicht geschrieben werden:`, error instanceof Error ? error.message : error);
    return null;
  }
}

export const USAGE_THRESHOLDS = [80, 100] as const;

/* usage.threshold (80 %, 100 %) je einmal pro Periode; Merker sind die vorhandenen Outbox-Events der Periode
 * (kein neues Feld in usage_periods). Aufruf nach jeder Kontingent-Prüfung (Upload-Token, API). */
export async function noteUsageThresholds(workspaceId: string, quota: QuotaState): Promise<number[]> {
  if (!quota.usage || quota.included_minutes <= 0) return [];
  const percent = (quota.used_minutes / quota.included_minutes) * 100;
  const emitted: number[] = [];
  const repo = getApiRepo();
  for (const threshold of USAGE_THRESHOLDS) {
    if (percent < threshold) continue;
    const match = { period_start: quota.usage.period_start, threshold: String(threshold) };
    try {
      if (await repo.hasOutboxEvent(workspaceId, "usage.threshold", match)) continue;
    } catch {
      continue;
    }
    const event = await emitOutbox(workspaceId, "usage.threshold", "usage_period", quota.usage.id, {
      period_start: quota.usage.period_start,
      period_end: quota.usage.period_end,
      threshold: String(threshold),
      percent: Math.round(percent),
      used_source_minutes: quota.used_minutes,
      included_minutes: quota.included_minutes,
      allow_overage: quota.allow_overage,
    });
    if (event) emitted.push(threshold);
  }
  return emitted;
}
