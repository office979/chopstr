import "server-only";
import { getRepo } from "@/lib/repo";
import { getApiRepo } from "@/lib/repo/api";
import type { Publication } from "@/lib/repo/types-api";
import { isUuidShape } from "@/lib/api/lookup";

export type StopTrackingOutcome =
  | { ok: true; publication: Publication; changed: boolean }
  | { ok: false; status: 404 | 409; code: string; message: string };

/* „Nicht mehr messen“ (Review R1-06): ein verfolgter Link bekommt tracking off und keinen Termin mehr.
 * Nichts wird gelöscht, Messreihe und Fenster bleiben lesbar. Nur für tracking link; OAuth-Publikationen
 * misst der PublishWorkflow in festen Fenstern, das steuert dieser Schalter nicht. Ein zweiter Aufruf ist
 * harmlos (changed false). Gemeinsam für PATCH /api/v1/publications/{id} und die Sitzungsroute. */
export async function stopTracking(input: { publicationId: string; via: "api" | "ui"; apiKeyId?: string }): Promise<StopTrackingOutcome> {
  const notFound = { ok: false as const, status: 404 as const, code: "not_found", message: "Publikation nicht gefunden." };
  if (!isUuidShape(input.publicationId)) return notFound;
  const repo = getApiRepo();
  const current = await repo.getPublication(input.publicationId);
  if (!current) return notFound;
  if (current.tracking === "off") return { ok: true, publication: current, changed: false };
  if (current.tracking !== "link") {
    return { ok: false, status: 409, code: "tracking_not_link", message: "Abschalten geht nur für verfolgte Links." };
  }
  const updated = await repo.stopLinkTracking(current.id);
  if (!updated) return { ok: true, publication: { ...current, tracking: "off", next_snapshot_at: null }, changed: false };
  await getRepo().audit({
    action: "publication.tracking_stopped",
    entity: "publications",
    entity_id: updated.id,
    payload: { clip_id: updated.clip_id, platform: updated.platform, external_id: updated.external_id, via: input.via, ...(input.apiKeyId ? { api_key_id: input.apiKeyId } : {}) },
  });
  return { ok: true, publication: updated, changed: true };
}
