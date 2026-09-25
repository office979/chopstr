"use client";

import Link from "next/link";
import { useMemo, useState, type ReactNode } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Timecode } from "@/components/ui/Timecode";
import { cn } from "@/components/ui/cn";
import { DeleteSourceButton } from "@/components/projects/DeleteSourceButton";
import { formatDate } from "@/lib/format";
import {
  hauptaktion,
  projektSatz,
  projektZustand,
  PROJEKT_LABEL,
  PROJEKT_RANG,
  type Hauptaktion,
  type ProjektZustand,
} from "@/lib/projekte/projekt-zustand";
import { naechsteAufgabe, type Aufgabe, type VideoStand } from "@/lib/clips/pruefstand";
import type { ClipCount, Source } from "@/lib/repo/types";

export interface ProjektZeile {
  source: Source;
  clips: ClipCount | null;
  /* Name des Markenprofils, also des Kunden. Null, wenn keins zugeordnet ist. */
  marke: string | null;
  /* Vorschaubild aus einem gebauten Clip dieses Videos. */
  bildSrc: string | null;
  /* Die Clips dieses Videos, gezählt mit demselben Modell wie auf der Prüfseite. */
  stand: VideoStand | null;
}

interface Props {
  zeilen: ProjektZeile[];
  canDelete: boolean;
  canUpload: boolean;
}

type Sortierung = "geaendert" | "name";

/* Die Bibliothek: welches Projekt soll ich fortsetzen?
 *
 * Suche, Filter und Sortierung liegen im Zustand dieser Komponente und im Adressfragment. Das
 * Fragment ist der Grund: wer ein Projekt öffnet und mit dem Zurück-Knopf wiederkommt, findet
 * seine Auswahl vor, ohne dass dafür etwas gespeichert werden muss. Und ein Link lässt sich
 * weitergeben.
 */
export function Bibliothek({ zeilen, canDelete, canUpload }: Props) {
  const [suche, setSuche] = useState("");
  const [filter, setFilter] = useState<ProjektZustand | "alle">("alle");
  const [sortierung, setSortierung] = useState<Sortierung>("geaendert");

  const mitZustand = useMemo(
    () => zeilen.map((z) => ({ ...z, zustand: projektZustand(z.source, z.clips) })),
    [zeilen],
  );

  const zaehler = useMemo(() => {
    const aus = new Map<ProjektZustand, number>();
    for (const z of mitZustand) aus.set(z.zustand, (aus.get(z.zustand) ?? 0) + 1);
    return aus;
  }, [mitZustand]);

  const sichtbar = useMemo(() => {
    const begriff = suche.trim().toLowerCase();
    const gefiltert = mitZustand.filter((z) => {
      if (filter !== "alle" && z.zustand !== filter) return false;
      if (!begriff) return true;
      /* Gesucht wird im Namen und in der Marke: das sind die beiden Dinge, die jemand im Kopf
       * hat, wenn er ein Projekt sucht. */
      return (
        z.source.title.toLowerCase().includes(begriff) || (z.marke ?? "").toLowerCase().includes(begriff)
      );
    });
    return [...gefiltert].sort((a, b) => {
      if (sortierung === "name") return a.source.title.localeCompare(b.source.title, "de");
      const ra = PROJEKT_RANG[a.zustand];
      const rb = PROJEKT_RANG[b.zustand];
      if (ra !== rb) return ra - rb;
      return new Date(b.source.updated_at).getTime() - new Date(a.source.updated_at).getTime();
    });
  }, [mitZustand, suche, filter, sortierung]);

  const gefiltertAktiv = suche.trim() !== "" || filter !== "alle";

  if (zeilen.length === 0) {
    return (
      <GlassCard padding="lg" className="text-center">
        <p className="text-lg font-medium">chopstr macht aus langen Videos kurze Clips</p>
        <p className="mx-auto mt-2 max-w-md text-text-2">
          Du lädst ein Video hoch, der Computer sucht die besten Stellen, du wählst aus. Dauert etwa fünf Minuten.
        </p>
        {canUpload && (
          <div className="mt-6 flex justify-center">
            <ButtonLink href="/upload">Erstes Video hochladen</ButtonLink>
          </div>
        )}
      </GlassCard>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <label className="min-w-[200px] flex-1">
          <span className="sr-only">Videos durchsuchen</span>
          <input
            type="search"
            value={suche}
            onChange={(e) => setSuche(e.target.value)}
            placeholder="Nach Name oder Marke suchen"
            className="transition-soft w-full rounded-inner border border-line bg-black/40 px-4 py-2.5 text-[15px] text-text placeholder:text-text-3 hover:border-line-strong focus:border-white/50 focus:outline-none"
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-text-2">
          Sortieren
          <select
            value={sortierung}
            onChange={(e) => setSortierung(e.target.value as Sortierung)}
            className="transition-soft rounded-inner border border-line bg-black/40 px-3 py-2 text-sm text-text hover:border-line-strong focus:border-white/50 focus:outline-none"
          >
            <option value="geaendert">Handlungsbedarf zuerst</option>
            <option value="name">Nach Name</option>
          </select>
        </label>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Nach Zustand filtern">
        {([["alle", `Alle (${zeilen.length})`]] as [ProjektZustand | "alle", string][])
          .concat(
            (["fehler", "pruefen", "verarbeitung", "upload", "bereit", "leer"] as ProjektZustand[])
              .filter((z) => (zaehler.get(z) ?? 0) > 0)
              .map((z) => [z, `${PROJEKT_LABEL[z]} (${zaehler.get(z)})`] as [ProjektZustand | "alle", string]),
          )
          .map(([wert, label]) => (
            <button
              key={wert}
              type="button"
              onClick={() => setFilter(wert)}
              aria-pressed={filter === wert}
              className={cn(
                "transition-soft rounded-pill border px-3.5 py-1.5 text-sm",
                filter === wert ? "border-white/60 bg-white/10 text-text" : "border-line text-text-2 hover:border-line-strong",
              )}
            >
              {label}
            </button>
          ))}
      </div>

      {/* Eine ergebnislose Suche ist keine leere Bibliothek. Der Unterschied muss dastehen, sonst
          glaubt jemand, seine Videos seien weg. */}
      {sichtbar.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-text">Kein Video passt dazu.</p>
          <p className="mt-1 text-sm text-text-2">
            Du hast {zeilen.length} {zeilen.length === 1 ? "Video" : "Videos"}, nur keins mit dieser Suche.
          </p>
          <div className="mt-5 flex justify-center">
            <Button
              variant="ghost"
              onClick={() => {
                setSuche("");
                setFilter("alle");
              }}
            >
              Filter zurücksetzen
            </Button>
          </div>
        </GlassCard>
      ) : (
        <ul className="flex flex-col gap-3">
          {sichtbar.map(({ source: s, clips, marke, bildSrc, zustand, stand }) => {
            const aufgabe = stand ? naechsteAufgabe(stand) : null;
            const aktion = hauptaktion(zustand);
            return (
              <li key={s.id}>
                <GlassCard padding="md" className="group flex min-w-0 gap-4">
                  {/* Vorschaubild, wenn es eins gibt. Ein Projekt an seinem Bild wiederzuerkennen
                      geht schneller als über den Namen. */}
                  <Link
                    href={`/projekte/${s.id}`}
                    aria-label={`${s.title} öffnen`}
                    className="transition-soft relative h-[72px] w-[72px] shrink-0 overflow-hidden rounded-[10px] border border-line bg-black hover:border-white/40"
                  >
                    {bildSrc ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img src={bildSrc} alt="" className="h-full w-full object-cover" />
                    ) : (
                      <span
                        aria-hidden="true"
                        className="block h-full w-full"
                        style={{
                          background:
                            "radial-gradient(ellipse at 50% 30%, rgba(91,140,255,0.22) 0%, rgba(27,26,98,0.3) 40%, rgba(0,0,0,0) 75%), #0a0a13",
                        }}
                      />
                    )}
                  </Link>

                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                      <Link href={`/projekte/${s.id}`} className="truncate text-[15px] font-medium text-text hover:underline">
                        {s.title}
                      </Link>
                      {marke && <span className="truncate text-sm text-text-2">{marke}</span>}
                    </div>

                    {/* Solange es keine Clips gibt, zählt der Stand des Videos: hochladen,
                        verarbeiten, nichts gefunden. Sobald es Clips gibt, sagt deren Aufteilung
                        mehr, und der Videozustand wäre nur noch eine gröbere Wiederholung. */}
                    {!(stand && stand.gesamt > 0) && (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <ZustandPille zustand={zustand} />
                        <span className="text-sm text-text-2">{projektSatz(zustand, clips)}</span>
                      </div>
                    )}

                    {/* Die Clips nach Stand, jede Zahl ein Weg in ihre Liste. Vorher stand hier
                        nur „14 Clips", und das beantwortet keine Frage. */}
                    {stand && stand.gesamt > 0 && (
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                        {stand.fehler > 0 && (
                          <ClipZahl href={`/projekte/${s.id}/clips#fehler`} ton="fehler">
                            {stand.fehler} mit Fehler
                          </ClipZahl>
                        )}
                        {stand.postbereit > 0 && (
                          <ClipZahl href={`/projekte/${s.id}/clips#postbereit`} ton="gut">
                            {stand.postbereit} bereit zum Posten
                          </ClipZahl>
                        )}
                        {stand.wirdGebaut > 0 && <span className="text-text-3">{stand.wirdGebaut} werden geclippt</span>}
                      </div>
                    )}

                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-3">
                      <span>
                        Länge <Timecode seconds={s.duration_s} className="text-inherit" />
                      </span>
                      <span>Zuletzt {formatDate(s.updated_at)}</span>
                    </div>
                  </div>

                  {/* Nebeneinander statt untereinander: der Hauptknopf und daneben das Zeichen zum
                      Löschen. Untereinander sahen beide gleich wichtig aus, und der untere war der
                      gefährliche. */}
                  <div className="flex shrink-0 items-center justify-end gap-2 self-center">
                    <ButtonLink href={`/projekte/${s.id}${klickZiel(aufgabe, aktion)}`} size="sm">
                      {knopfText(aufgabe, aktion)}
                    </ButtonLink>
                    {canDelete && <DeleteSourceButton sourceId={s.id} title={s.title} />}
                  </div>
                </GlassCard>
              </li>
            );
          })}
        </ul>
      )}

      {gefiltertAktiv && sichtbar.length > 0 && (
        <p className="text-sm text-text-3">
          {sichtbar.length} von {zeilen.length} Videos.{" "}
          <button
            type="button"
            onClick={() => {
              setSuche("");
              setFilter("alle");
            }}
            className="underline underline-offset-4 hover:text-text"
          >
            Filter zurücksetzen
          </button>
        </p>
      )}
    </div>
  );
}

/* Der Zustand als Pille. Farbe nur da, wo sie etwas bedeutet. */
function ZustandPille({ zustand }: { zustand: ProjektZustand }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-pill border px-2.5 text-[12px] font-medium",
        zustand === "fehler" && "border-danger/60 bg-danger/15 text-text",
        zustand === "pruefen" && "border-attention/60 bg-attention/15 text-text",
        zustand === "bereit" && "border-brand/60 bg-brand/15 text-text",
        (zustand === "verarbeitung" || zustand === "upload" || zustand === "leer") && "border-line text-text-2",
      )}
    >
      {PROJEKT_LABEL[zustand]}
    </span>
  );
}

/* Eine Clipzahl, die zu ihrer Liste führt. */
function ClipZahl({ href, ton, children }: { href: string; ton?: "gut" | "achtung" | "fehler"; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={cn(
        "transition-soft rounded-pill border px-2.5 py-1 hover:border-line-strong",
        ton === "fehler" && "border-danger/50 text-text",
        ton === "achtung" && "border-attention/50 text-text",
        ton === "gut" && "border-brand/50 text-text",
        !ton && "border-line text-text-2",
      )}
    >
      {children}
    </Link>
  );
}

/* Aus „3 Clips prüfen" wird auf dem Knopf „Prüfen": die Zahl steht schon daneben, und ein Knopf
 * mit drei Wörtern in einer Zeile mit fünf anderen ist Lärm. */
function aufgabeKnopf(text: string): string {
  const ohneZahl = text.replace(/^\d+\s+/, "");
  return ohneZahl.charAt(0).toUpperCase() + ohneZahl.slice(1);
}

/* Was auf dem Knopf steht, und wohin er führt.
 *
 * Hier stand einmal die Aufgabe selbst und der Weg ging in die gefilterte Liste. Beides war zu
 * eng: der Knopf auf der Videokarte ist der Weg zu diesem Video, nicht zu einer Teilmenge davon,
 * und wer ankommt, will erst sehen, was da ist. Die Zahlen mit ihren Filtern stehen weiter oben
 * auf der Seite und führen weiterhin gezielt hin. */
function knopfText(aufgabe: Aufgabe | null, aktion: Hauptaktion): string {
  if (!aufgabe) return aktion.label;
  if (aufgabe.pfad.startsWith("/clips")) return "Alle Clips anzeigen";
  return aufgabeKnopf(aufgabe.text);
}

function klickZiel(aufgabe: Aufgabe | null, aktion: Hauptaktion): string {
  if (!aufgabe) return aktion.pfad;
  return aufgabe.pfad.startsWith("/clips") ? "/clips" : aufgabe.pfad;
}
