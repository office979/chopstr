"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { formatDate } from "@/lib/format";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import type { Platform } from "@/lib/repo/types";

/* Was aus einem geposteten Clip geworden ist, und wie die Zahlen hereinkommen.
 *
 * Bis hierher endete die Kette am fertigen Clip. Posten und Kennzahlen gab es nur als
 * Schnittstelle: POST auf publish und auf metrics, beides vollständig gebaut, beides ohne
 * Oberfläche. Wer chopstr benutzte, konnte also einen Clip herunterladen und posten - aber
 * nirgends eintragen, dass er das getan hat. Dadurch blieben zwei ganze Seiten für immer leer:
 * „Tests" braucht Folgezahlen, um zwei Einstiege zu vergleichen, und „Berichte" braucht sie, um
 * eine Woche zu bewerten. Beide standen da und konnten nie etwas zeigen.
 *
 * Hier ist der fehlende Teil: eintragen, dass gepostet wurde, und danach die Zahlen nachtragen.
 * Von Hand, weil chopstr nicht selbst postet - das ist eine bewusste Entscheidung des Produkts
 * und keine Lücke.
 */

interface Publikation {
  id: string;
  platform: string;
  status: string;
  external_url: string | null;
  published_at: string | null;
  created_at: string;
}

interface Rueckmeldung {
  publication_id: string | null;
  views: number | null;
  follows: number | null;
  follows_per_1k: number | null;
}

interface Verbindung {
  id: string;
  platform: string;
  account_label: string;
  status: string;
}

/* Die Zahlen, die jemand aus der Plattform abschreibt. Bewusst wenige: wer sechs Felder sieht,
 * füllt keins aus. Aufrufe und neue Folgende reichen für den Bericht und für einen Vergleich
 * zweier Einstiege. */
const FELDER = [
  { key: "views", name: "Aufrufe", hinweis: "So oft wurde das Video gestartet." },
  { key: "follows", name: "Neue Folgende", hinweis: "Wie viele sind dir danach gefolgt?" },
  { key: "likes", name: "Gefällt mir", hinweis: "" },
  { key: "comments", name: "Kommentare", hinweis: "" },
] as const;

export function Gepostet({
  sourceId,
  clipId,
  plattform,
  canPublish,
}: {
  sourceId: string;
  clipId: string;
  plattform: Platform;
  canPublish: boolean;
}) {
  const [publikationen, setPublikationen] = useState<Publikation[]>([]);
  const [zahlen, setZahlen] = useState<Rueckmeldung[]>([]);
  const [verbindungen, setVerbindungen] = useState<Verbindung[]>([]);
  const [geladen, setGeladen] = useState(false);
  const [offen, setOffen] = useState(false);
  const [zahlenFuer, setZahlenFuer] = useState<Publikation | null>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [eingabe, setEingabe] = useState<Record<string, string>>({});

  const laden = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/publish`);
      const d = (await res.json()) as { publications?: Publikation[]; feedback?: Rueckmeldung[]; connections?: Verbindung[] };
      if (res.ok) {
        setPublikationen(d.publications ?? []);
        setZahlen(d.feedback ?? []);
        setVerbindungen(d.connections ?? []);
      }
    } catch {
      /* Ohne Antwort bleibt der Bereich leer; das ist kein Grund, die Seite zu stören. */
    } finally {
      setGeladen(true);
    }
  }, [sourceId, clipId]);

  useEffect(() => {
    /* Ein Tick später, damit das Setzen des Zustands nicht in denselben Durchgang fällt wie der
     * erste Aufbau - React verbietet das aus gutem Grund, es erzeugt sonst eine zweite Runde. */
    const t = window.setTimeout(() => void laden(), 0);
    return () => window.clearTimeout(t);
  }, [laden]);

  /* Eine Verbindung „manual" ist die Art, wie chopstr „ich poste selbst" ablegt. Fehlt sie, wird
   * sie beim ersten Eintragen angelegt - der Nutzer soll dafür nicht erst in die Einstellungen
   * geschickt werden, nur damit eine Zeile in einer Tabelle entsteht. */
  const eigeneVerbindung = verbindungen.find((v) => v.platform === "manual" && v.status === "connected");

  const eintragen = async () => {
    setBusy(true);
    setFehler(null);
    try {
      let verbindung = eigeneVerbindung?.id;
      if (!verbindung) {
        const res = await fetch("/api/publishing/connections", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ account_label: "Ich poste selbst" }),
        });
        const d = (await res.json()) as { error?: string; connection?: { id: string } };
        if (!res.ok || !d.connection) throw new Error(d.error ?? "Das hat nicht geklappt");
        verbindung = d.connection.id;
      }
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: true, connection_id: verbindung, external_url: link.trim() || undefined }),
      });
      const d = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(d.error ?? "Das hat nicht geklappt");
      setOffen(false);
      setLink("");
      await laden();
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Das hat nicht geklappt");
    } finally {
      setBusy(false);
    }
  };

  const zahlenSpeichern = async () => {
    if (!zahlenFuer) return;
    setBusy(true);
    setFehler(null);
    try {
      const res = await fetch(`/api/publishing/publications/${zahlenFuer.id}/metrics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(eingabe),
      });
      const d = (await res.json()) as { error?: string };
      if (!res.ok) throw new Error(d.error ?? "Das hat nicht geklappt");
      setZahlenFuer(null);
      setEingabe({});
      await laden();
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Das hat nicht geklappt");
    } finally {
      setBusy(false);
    }
  };

  if (!geladen) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {publikationen.length === 0 ? (
        canPublish && (
          <button
            type="button"
            onClick={() => setOffen(true)}
            className="text-xs text-text-2 underline underline-offset-4 hover:text-text"
          >
            Als gepostet eintragen
          </button>
        )
      ) : (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          {publikationen.map((p) => {
            const z = zahlen.find((f) => f.publication_id === p.id);
            return (
              <span key={p.id} className="flex items-center gap-2">
                <span className="text-text-2">
                  Gepostet auf {PLATFORM_LABELS[p.platform as Platform] ?? p.platform}
                  {p.published_at ? ` am ${formatDate(p.published_at)}` : ""}
                </span>
                {z && z.views != null ? (
                  <span className="text-text">
                    {z.views.toLocaleString("de-AT")} Aufrufe
                    {z.follows != null ? `, ${z.follows.toLocaleString("de-AT")} neue Folgende` : ""}
                  </span>
                ) : (
                  canPublish && (
                    <button
                      type="button"
                      onClick={() => {
                        setZahlenFuer(p);
                        setEingabe({});
                      }}
                      className="text-text-2 underline underline-offset-4 hover:text-text"
                    >
                      Zahlen eintragen
                    </button>
                  )
                )}
              </span>
            );
          })}
        </div>
      )}

      <Modal
        open={offen}
        onClose={() => !busy && setOffen(false)}
        title="Als gepostet eintragen"
        description={`Du hast den Clip selbst auf ${PLATFORM_LABELS[plattform]} gepostet. Trag das hier ein, dann kannst du später die Zahlen dazuschreiben - und chopstr kann daraus lernen, was bei dir ankommt.`}
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-text">Link zum Beitrag</span>
            <span className="text-xs text-text-3">Freiwillig. Hilft, ihn später wiederzufinden.</span>
            <input
              type="url"
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://"
              className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
            />
          </label>
          {fehler && <p className="text-sm text-attention">{fehler}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setOffen(false)} disabled={busy}>
              Abbrechen
            </Button>
            <Button onClick={() => void eintragen()} disabled={busy}>
              {busy ? "Wird eingetragen" : "Eintragen"}
            </Button>
          </div>
        </div>
      </Modal>

      <Modal
        open={zahlenFuer != null}
        onClose={() => !busy && setZahlenFuer(null)}
        title="Zahlen eintragen"
        description="Schreib ab, was die Plattform dir zeigt. Du musst nicht alles ausfüllen - Aufrufe und neue Folgende reichen für den Wochenbericht."
      >
        <div className="flex flex-col gap-4">
          <div className="grid gap-3 sm:grid-cols-2">
            {FELDER.map((f) => (
              <label key={f.key} className="flex flex-col gap-1">
                <span className="text-sm text-text">{f.name}</span>
                {f.hinweis && <span className="text-xs text-text-3">{f.hinweis}</span>}
                <input
                  type="text"
                  inputMode="numeric"
                  value={eingabe[f.key] ?? ""}
                  onChange={(e) => setEingabe((v) => ({ ...v, [f.key]: e.target.value }))}
                  className="transition-soft rounded-inner border border-line bg-black/40 px-3 py-2 text-[15px] tabular-nums text-text hover:border-line-strong focus:border-white/50 focus:outline-none"
                />
              </label>
            ))}
          </div>
          {fehler && <p className="text-sm text-attention">{fehler}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setZahlenFuer(null)} disabled={busy}>
              Abbrechen
            </Button>
            <Button onClick={() => void zahlenSpeichern()} disabled={busy}>
              {busy ? "Wird gespeichert" : "Speichern"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
