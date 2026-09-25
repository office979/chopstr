/* Die Gastfreigabe: wann eine erteilte Freigabe nicht mehr gilt. Reine Rechnung, deshalb hier.
 *
 * Ob der Download gesperrt ist, stand auch einmal hier. Die Frage gibt es nicht mehr: die
 * Freigabe sperrt ihn nie. Was sie sperrt, ist das Posten - siehe ausgabe.test. */

import { describe, expect, it } from "vitest";
import { freigabeVeraltet } from "@/lib/guest/approval";
import type { GuestApproval } from "@/lib/repo/types";


/* Eine Freigabe gilt der Fassung, die der Gast gesehen hat.
 *
 * Wird danach geschnitten oder der Text geändert, deckt seine Zusage das nicht mehr. Das ist
 * keine Formalie: die Person hat der Veröffentlichung von etwas zugestimmt, das so nicht mehr
 * existiert. */
describe("freigabeVeraltet", () => {
  const freigabe = (over: Partial<GuestApproval> = {}) =>
    ({ decision: "approved", decided_at: "2026-09-20T10:00:00.000Z", ...over }) as GuestApproval;

  it("schlägt an, wenn der Clip nach der Freigabe geändert wurde", () => {
    expect(freigabeVeraltet(freigabe(), "2026-09-21T09:00:00.000Z")).toBe(true);
  });

  it("schweigt, wenn seit der Freigabe nichts passiert ist", () => {
    expect(freigabeVeraltet(freigabe(), "2026-09-20T09:00:00.000Z")).toBe(false);
  });

  it("stört sich nicht am Speichern der Entscheidung selbst", () => {
    /* Das Setzen der Entscheidung rührt den Clip an; eine Sekunde Luft. */
    expect(freigabeVeraltet(freigabe(), "2026-09-20T10:00:00.500Z")).toBe(false);
  });

  it("gilt nur für eine erteilte Freigabe", () => {
    expect(freigabeVeraltet(freigabe({ decision: "changes" }), "2026-09-21T09:00:00.000Z")).toBe(false);
    expect(freigabeVeraltet(undefined, "2026-09-21T09:00:00.000Z")).toBe(false);
  });

  it("behauptet nichts ohne Änderungsdatum", () => {
    expect(freigabeVeraltet(freigabe(), null)).toBe(false);
  });
});
