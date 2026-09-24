/* Welche Dateien der Upload annimmt.
 *
 * Die Liste steht an zwei Stellen: in der Oberfläche (was zur Auswahl steht) und an der
 * Schnittstelle (welche Endung die gespeicherte Datei bekommt). Laufen sie auseinander, nimmt
 * die eine Seite etwas an, mit dem die andere nichts anfangen kann. */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const WURZEL = resolve(__dirname, "..", "..", "..");

function lies(pfad: string): string {
  return readFileSync(resolve(WURZEL, pfad), "utf8");
}

describe("Formate", () => {
  const form = lies("apps/web/app/upload/UploadForm.tsx");
  const route = lies("apps/web/app/api/uploads/direct/route.ts");

  const ausForm = [...(/const ENDUNGEN = \[([^\]]+)\]/.exec(form)?.[1] ?? "").matchAll(/"(\.[a-z0-9]+)"/g)].map(
    (m) => m[1],
  );
  const ausRoute = [...(/const EXT_BY_MIME[^}]+}/.exec(route)?.[0] ?? "").matchAll(/"(\.[a-z0-9]+)"/g)].map((m) => m[1]);

  it("die Oberfläche nennt überhaupt Formate", () => {
    expect(ausForm.length).toBeGreaterThan(3);
  });

  it("bietet nichts an, was die Schnittstelle nicht kennt", () => {
    /* Sonst nimmt die Oberfläche eine Datei an, die beim Speichern ohne Endung landet und die
     * der Worker nicht öffnen kann. */
    for (const e of ausForm) {
      expect(ausRoute, `${e} fehlt in EXT_BY_MIME`).toContain(e);
    }
  });

  it("prüft die Endung und nicht den gemeldeten Typ", () => {
    /* Browser melden für dieselbe Datei verschiedene Typen, manche gar keinen. Beim Ziehen in
     * die Fläche greift das accept-Attribut ohnehin nicht. */
    expect(form).toContain("function endungPasst");
    expect(form).toMatch(/endungPasst\(f\.name\)/);
  });

  it("täuscht keinen Upload mehr vor, wenn der Dienst nicht erreichbar ist", () => {
    /* Vorher lief bei einem nicht erreichbaren Endpunkt ein Balken durch und danach entstand ein
     * Demo-Projekt: der Nutzer glaubte, seine Datei liege auf dem Server. */
    const stelle = form.slice(form.indexOf("await realUpload("));
    expect(stelle.slice(0, 900)).not.toContain("simulateUpload");
  });

  it("räumt beim Abbrechen auf", () => {
    /* ``abort(true)`` sagt dem Server, dass der angefangene Upload weg kann. */
    expect(form).toContain("upload.abort(true)");
  });

  it("kann einen angefangenen Upload fortsetzen", () => {
    expect(form).toContain("findPreviousUploads");
    expect(form).toContain("resumeFromPreviousUpload");
  });

  it("sperrt den zweiten Klick sofort", () => {
    /* Der Knopf ist zwar ``disabled``, sobald der Upload läuft, aber das greift erst nach dem
     * nächsten Aufbau. Zwei Klicks im selben Moment kämen daran vorbei. */
    expect(form).toMatch(/if \(laeuftRef\.current\) return;/);
    expect(form).toContain("laeuftRef.current = true;");
  });
});

describe("Doppelte Aufträge", () => {
  const finalize = lies("apps/web/lib/uploads/finalize.ts");

  it("gibt bei einem zweiten Aufruf dieselbe Quelle zurück", () => {
    /* Der Verweis des Clients ist die Kennung der Quelle. Ein zweiter Klick, ein
     * Wiederholungsversuch oder ein doppelt gefeuerter Hook darf kein zweites Projekt anlegen
     * und nicht am doppelten Schlüssel scheitern. */
    expect(finalize).toMatch(/if \(pending && pending\.status !== "uploading"\) \{[\s\S]{0,200}return \{ source_id: pending\.id/);
  });
});
