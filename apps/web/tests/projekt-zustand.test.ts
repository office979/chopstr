/* Der Zustand eines Projekts in der Bibliothek.
 *
 * Vorher stand dort der Stand der Maschine („Computer bewertet die Stellen", „Fertig"). Ein
 * Projekt mit sechs ungeprüften Clips und eines, bei dem alles freigegeben ist, sahen gleich aus. */

import { describe, expect, it } from "vitest";
import {
  hauptaktion,
  projektSatz,
  projektZustand,
  PROJEKT_LABEL,
  PROJEKT_RANG,
  type ProjektZustand,
} from "@/lib/projekte/projekt-zustand";
import type { ClipCount, Source } from "@/lib/repo/types";

const quelle = (status: Source["status"]): Source => ({ status }) as Source;

const zaehler = (over: Partial<ClipCount> = {}): ClipCount => ({
  total: 0,
  rendered: 0,
  rendering: 0,
  failed: 0,
  offen: 0,
  bereit: 0,
  verworfen: 0,
  ...over,
});

describe("projektZustand", () => {
  it("zeigt den laufenden Upload", () => {
    expect(projektZustand(quelle("uploading"), null)).toBe("upload");
  });

  it("fasst alle Verarbeitungsschritte zu einem Zustand zusammen", () => {
    /* Ob der Computer gerade zuhört oder bewertet, ändert für den Nutzer nichts: er wartet. Die
     * Einzelschritte stehen auf der Projektseite. */
    for (const s of ["uploaded", "ingesting", "transcribing", "analyzing", "scoring"] as const) {
      expect(projektZustand(quelle(s), null), s).toBe("verarbeitung");
    }
  });

  it("bleibt in der Verarbeitung, solange Clips gebaut werden", () => {
    expect(projektZustand(quelle("ready"), zaehler({ total: 3, rendering: 1 }))).toBe("verarbeitung");
  });

  it("verlangt eine Prüfung, solange Clips offen sind", () => {
    expect(projektZustand(quelle("ready"), zaehler({ total: 3, rendered: 3, offen: 2, bereit: 1 }))).toBe("pruefen");
  });

  it("ist bereit, wenn über alle Clips entschieden wurde", () => {
    expect(projektZustand(quelle("ready"), zaehler({ total: 3, rendered: 3, bereit: 3 }))).toBe("bereit");
  });

  it("zählt einen verworfenen Clip nicht als offen", () => {
    /* Sonst stünde ein Projekt, in dem jemand aufgeräumt hat, für immer auf „Bitte prüfen". */
    expect(projektZustand(quelle("ready"), zaehler({ total: 2, rendered: 2, bereit: 1, verworfen: 1 }))).toBe("bereit");
  });

  it("sagt es, wenn nichts gefunden wurde", () => {
    expect(projektZustand(quelle("ready"), zaehler())).toBe("leer");
    expect(projektZustand(quelle("ready"), null)).toBe("leer");
  });

  it("stellt den Fehler über alles", () => {
    expect(projektZustand(quelle("failed"), zaehler({ total: 3, rendered: 3, bereit: 3 }))).toBe("fehler");
  });
});

describe("hauptaktion", () => {
  it("führt bei offenen Clips zu den Clips", () => {
    expect(hauptaktion("pruefen")).toEqual({ label: "Clips prüfen", pfad: "/clips" });
  });

  it("führt ohne Fund in den Text", () => {
    /* Dort lässt sich sehen, woran es lag. Zu den Clips zu führen, die es nicht gibt, wäre eine
     * Sackgasse. */
    expect(hauptaktion("leer").pfad).toBe("/transkript");
  });

  it("gibt für jeden Zustand genau eine Handlung mit Beschriftung", () => {
    for (const z of Object.keys(PROJEKT_LABEL) as ProjektZustand[]) {
      expect(hauptaktion(z).label.length).toBeGreaterThan(3);
    }
  });
});

describe("projektSatz", () => {
  it("nennt die Zahl der wartenden Clips", () => {
    expect(projektSatz("pruefen", zaehler({ offen: 3 }))).toContain("3 Clips warten");
    expect(projektSatz("pruefen", zaehler({ offen: 1 }))).toContain("Ein Clip wartet");
  });

  it("nennt beim Bauen, wie viele gerade entstehen", () => {
    expect(projektSatz("verarbeitung", zaehler({ rendering: 2 }))).toContain("2 Clips werden");
  });
});

describe("Reihenfolge", () => {
  it("stellt nach vorn, was Arbeit macht", () => {
    expect(PROJEKT_RANG.fehler).toBeLessThan(PROJEKT_RANG.pruefen);
    expect(PROJEKT_RANG.pruefen).toBeLessThan(PROJEKT_RANG.bereit);
    expect(PROJEKT_RANG.bereit).toBeLessThan(PROJEKT_RANG.leer);
  });
});
