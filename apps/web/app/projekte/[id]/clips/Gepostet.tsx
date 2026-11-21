"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import { publicationRow, type RowFeedback, type RowPublication, type RowSnapshot } from "@/lib/publishing/publication-row";
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
 *
 * Je Publikation eine Zeile (lib/publishing/publication-row.ts): Plattform mit Link zum Beitrag, die
 * letzte Zahl mit Zeitpunkt rechts und der Status in Klartext, ob und bis wann gemessen wird. Nach drei
 * Zeilen klappt die Liste zu.
 */

type Publikation = RowPublication;
type Rueckmeldung = RowFeedback & { follows_per_1k: number | null };
interface Messstand {
  publication_id: string;
  latest: RowSnapshot | null;
  last: RowSnapshot | null;
}

/* So viele Zeilen sind sofort sichtbar, der Rest hinter „Alle anzeigen“ */
const SICHTBAR = 3;

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
  const [messstaende, setMessstaende] = useState<Messstand[]>([]);
  const [alle, setAlle] = useState(false);
  const [stoppt, setStoppt] = useState<string | null>(null);
  /* Zeitpunkt des letzten Ladens: danach richtet sich, ob eine Messdauer schon vorbei ist */
  const [jetzt, setJetzt] = useState(0);
  const [verbindungen, setVerbindungen] = useState<Verbindung[]>([]);
  const [geladen, setGeladen] = useState(false);
  const [offen, setOffen] = useState(false);
  const [zahlenFuer, setZahlenFuer] = useState<Publikation | null>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);
  const [eingabe, setEingabe] = useState<Record<string, string>>({});
  /* Link verfolgen: chopstr prüft den Link und misst danach von selbst (Worker, 30 Tage) */
  const [linkOffen, setLinkOffen] = useState(false);
  const [verfolgLink, setVerfolgLink] = useState("");
  const [ergebnis, setErgebnis] = useState<string[] | null>(null);
  const [linkHinweise, setLinkHinweise] = useState<string[]>([]);

  const laden = useCallback(async () => {
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/publish`);
      const d = (await res.json()) as { publications?: Publikation[]; feedback?: Rueckmeldung[]; snapshots?: Messstand[]; connections?: Verbindung[] };
      if (res.ok) {
        setPublikationen(d.publications ?? []);
        setZahlen(d.feedback ?? []);
        setMessstaende(d.snapshots ?? []);
        setJetzt(Date.now());
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
      void laden();
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Das hat nicht geklappt");
    } finally {
      setBusy(false);
    }
  };

  const linkVerfolgen = async () => {
    setBusy(true);
    setFehler(null);
    setErgebnis(null);
    setLinkHinweise([]);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/links`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: verfolgLink.trim() }),
      });
      const d = (await res.json()) as { error?: string; summary?: string[]; check?: { notes?: string[] } };
      const notes = d.check?.notes ?? [];
      if (!res.ok) {
        setLinkHinweise(notes.filter((n) => n !== d.error));
        throw new Error(d.error ?? "Das hat nicht geklappt");
      }
      setLinkHinweise(notes);
      setErgebnis(d.summary ?? []);
      setVerfolgLink("");
      /* Liste im Hintergrund neu laden: das Ergebnis steht schon, der Knopf soll nicht weiter „Wird geprüft“ zeigen */
      void laden();
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
      void laden();
    } catch (err) {
      setFehler(err instanceof Error ? err.message : "Das hat nicht geklappt");
    } finally {
      setBusy(false);
    }
  };

  const nichtMehrMessen = async (id: string) => {
    setStoppt(id);
    try {
      const res = await fetch(`/api/publishing/publications/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tracking: "off" }),
      });
      if (res.ok) await laden();
    } finally {
      setStoppt(null);
    }
  };

  if (!geladen) return null;

  const zeilen = publikationen.map((p) =>
    publicationRow(
      p,
      messstaende.find((m) => m.publication_id === p.id),
      zahlen.find((f) => f.publication_id === p.id),
      jetzt,
    ),
  );
  const sichtbar = alle ? zeilen : zeilen.slice(0, SICHTBAR);

  return (
    <div className="flex w-full flex-col gap-2">
      {zeilen.length > 0 && (
        <ul className="flex flex-col divide-y divide-line text-sm">
          {sichtbar.map((z) => {
            const p = publikationen.find((x) => x.id === z.id) as Publikation;
            return (
              <li key={z.id} className="flex items-start justify-between gap-3 py-2">
                <div className="flex min-w-0 flex-col gap-0.5">
                  {z.url ? (
                    <a href={z.url} target="_blank" rel="noopener noreferrer" className="truncate text-text underline-offset-4 hover:underline">
                      {z.platform}
                    </a>
                  ) : (
                    <span className="text-text">{z.platform}</span>
                  )}
                  {z.status && <span className={z.tone === "attention" ? "text-xs text-attention" : "text-xs text-text-2"}>{z.status}</span>}
                  {canPublish && (z.canEnterNumbers || z.canStop) && (
                    <span className="flex flex-wrap gap-x-3 text-xs">
                      {z.canEnterNumbers && (
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
                      )}
                      {z.canStop && (
                        <button
                          type="button"
                          onClick={() => void nichtMehrMessen(z.id)}
                          disabled={stoppt === z.id}
                          className="text-text-2 underline underline-offset-4 hover:text-text disabled:opacity-60"
                        >
                          {stoppt === z.id ? "Wird beendet" : "Nicht mehr messen"}
                        </button>
                      )}
                    </span>
                  )}
                </div>
                {z.number && (
                  <div className="flex shrink-0 flex-col items-end text-right">
                    <span className="tabular-nums text-text">{z.number}</span>
                    {z.numberAt && <span className="text-xs text-text-2">{z.numberAt}</span>}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
        {zeilen.length > SICHTBAR && (
          <button type="button" onClick={() => setAlle((a) => !a)} className="text-text-2 underline underline-offset-4 hover:text-text">
            {alle ? "Weniger anzeigen" : `Alle anzeigen (${zeilen.length})`}
          </button>
        )}
        {zeilen.length === 0 && canPublish && (
          <button type="button" onClick={() => setOffen(true)} className="text-text-2 underline underline-offset-4 hover:text-text">
            Als gepostet eintragen
          </button>
        )}
        {canPublish && (
          <button
            type="button"
            onClick={() => {
              setLinkOffen(true);
              setErgebnis(null);
              setLinkHinweise([]);
              setFehler(null);
            }}
            className="text-text-2 underline underline-offset-4 hover:text-text"
          >
            Link verfolgen
          </button>
        )}
      </div>

      <Modal
        open={linkOffen}
        onClose={() => !busy && setLinkOffen(false)}
        title="Link verfolgen"
        description="Füg den Link zum geposteten Beitrag ein. chopstr prüft ihn und holt danach die Zahlen von selbst."
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-text">Link einfügen</span>
            <span className="text-sm text-text-2">YouTube, TikTok, Instagram, X oder LinkedIn</span>
            <input
              type="url"
              value={verfolgLink}
              onChange={(e) => setVerfolgLink(e.target.value)}
              placeholder="https://"
              className="transition-soft rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
            />
          </label>
          {ergebnis && (
            <ul className="flex flex-col gap-1 text-sm text-text">
              {ergebnis.map((z) => (
                <li key={z}>{z}</li>
              ))}
            </ul>
          )}
          {linkHinweise.length > 0 && (
            <ul className="flex flex-col gap-1 text-sm text-text-2">
              {linkHinweise.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          )}
          {fehler && <p className="text-sm text-attention">{fehler}</p>}
          <div className="flex flex-wrap justify-end gap-2">
            {ergebnis ? (
              <Button onClick={() => setLinkOffen(false)}>Fertig</Button>
            ) : (
              <>
                <Button variant="ghost" onClick={() => setLinkOffen(false)} disabled={busy}>
                  Abbrechen
                </Button>
                <Button onClick={() => void linkVerfolgen()} disabled={busy || !verfolgLink.trim()}>
                  {busy ? "Wird geprüft" : "Link prüfen und verfolgen"}
                </Button>
              </>
            )}
          </div>
        </div>
      </Modal>

      <Modal
        open={offen}
        onClose={() => !busy && setOffen(false)}
        title="Als gepostet eintragen"
        description={`Du hast den Clip selbst auf ${PLATFORM_LABELS[plattform]} gepostet. Trag das hier ein, dann kannst du später die Zahlen dazuschreiben. So kann chopstr daraus lernen, was bei dir ankommt.`}
      >
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-text">Link zum Beitrag</span>
            <span className="text-sm text-text-2">Freiwillig. Mit Link prüft chopstr den Beitrag und holt die Zahlen, wo das geht.</span>
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
        description="Schreib ab, was die Plattform dir zeigt. Du musst nicht alles ausfüllen. Aufrufe und neue Folgende reichen für den Wochenbericht."
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
