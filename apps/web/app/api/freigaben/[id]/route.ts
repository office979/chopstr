import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* DELETE: eine Freigabe zurückziehen.
 *
 * Der Link wird damit ungültig - wer ihn öffnet, sieht „Link ungültig". Das ist der Sinn: eine
 * Freigabe zurückzuziehen heisst, dass niemand mehr darauf antworten soll.
 *
 * Die Urteile gehen mit (`on delete cascade`). Damit stehen die Clips wieder auf „Nicht
 * freigegeben" - also dort, wo sie vor dem Verschicken standen, und von dort lassen sie sich neu
 * verschicken. „Bestätigung ausstehend" wäre die falsche Auskunft: sie behauptet, jemand sei
 * gefragt worden und könne noch antworten, und beides stimmt nach dem Löschen nicht mehr.
 *
 * `guest_approval_required` wird zurückgesetzt, sonst bliebe der Download gesperrt an einem Clip,
 * zu dem es gar keine Frage mehr gibt.
 */
export async function DELETE(_request: Request, { params }: Params) {
  const auth = await requireApiRole("guest_approval.request");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();

  const weg = await repo.loescheFreigabe(id);
  if (!weg) return Response.json({ error: "Diese Freigabe gibt es nicht." }, { status: 404 });

  await repo.audit({ action: "guest_approval.requested", entity: "freigaben", entity_id: id, payload: { geloescht: true } });
  return Response.json({ ok: true });
}
