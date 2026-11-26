"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { LOOKS, mitVorgabe, type CaptionStyle } from "@/lib/clips/caption-style";
import { mediaUrl } from "@/lib/clips/labels";
import type { Candidate, Clip } from "@/lib/repo/types";

/* Die Ergebnisseite: alle Clips eines Videos, fertig zum Herunterladen.
 *
 * Vorher stand hier ein Prüfbrett mit Annehmen, Verwerfen, Untertitel-Studio, Bildausschnitt,
 * Gastfreigabe und Serien. Der Weg ist jetzt der, den alle grossen Clipping-Tools gehen:
 * hochladen, warten, Clips ansehen, herunterladen. Wer das Aussehen ändern will, ändert den Stil
 * für alle Clips des Videos auf einmal; jeder Clip wird danach neu gebaut. */

interface Props {
  sourceId: string;
  clips: Clip[];
  candidates: Candidate[];
  mediaBase: string | null;
  /* Im Testmodus gibt es keine gerenderten Dateien; die Vorschau zeigt dann den Ausschnitt aus dem Beispielvideo. */
  demoSrc: string | null;
  stilName: string | null;
  stilHref: string | null;
  aktuellerLook: string | null;
}

const LAEUFT = new Set(["draft", "approved", "rendering"]);
type Filter = "alle" | "9:16" | "16:9";

/* Ohne vorgeschlagenen Titel: der Anfang dessen, was gesagt wird, ohne Sprecher- und Satzmarken. */
function ersterSatz(text: string | undefined): string | null {
  if (!text) return null;
  const rein = text.replace(/\[\d+\]\s*\([^)]*\)\s*/g, " ").replace(/SPEAKER_\d+:?\s*/g, "").replace(/\s+/g, " ").trim();
  if (!rein) return null;
  const satz = rein.split(/(?<=[.!?])\s/)[0];
  return satz.length > 70 ? `${satz.slice(0, 68).trimEnd()}…` : satz;
}

function dauer(s: number): string {
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

export function ClipGallery({ sourceId, clips, candidates, mediaBase, demoSrc, stilName, stilHref, aktuellerLook }: Props) {
  const router = useRouter();
  const byCand = useMemo(() => new Map(candidates.map((c) => [c.id, c])), [candidates]);
  const formate = new Set(clips.map((c) => c.aspect));
  /* Bei zwei Formaten zuerst nur Hochformat: gemischte Kartenhöhen machen das Raster unruhig. */
  const [filter, setFilter] = useState<Filter>(formate.size > 1 ? "9:16" : "alle");
  const [stilOffen, setStilOffen] = useState(false);

  const sortiert = useMemo(() => {
    const score = (c: Clip) => (c.candidate_id ? byCand.get(c.candidate_id)?.total ?? 0 : 0);
    return [...clips]
      .filter((c) => c.status !== "deleted")
      .filter((c) => filter === "alle" || c.aspect === filter)
      .sort((a, b) => score(b) - score(a));
  }, [clips, byCand, filter]);

  const fertig = clips.filter((c) => c.status === "rendered" || c.status === "exported");
  const laufend = clips.filter((c) => LAEUFT.has(c.status)).length;

  /* Solange Clips gebaut werden, fragt die Seite alle drei Sekunden nach. Danach ist Ruhe. */
  useEffect(() => {
    if (laufend === 0) return;
    const iv = window.setInterval(() => router.refresh(), 3000);
    return () => window.clearInterval(iv);
  }, [laufend, router]);

  const alleLaden = () => {
    fertig.forEach((c, i) => {
      window.setTimeout(() => {
        const a = document.createElement("a");
        a.href = `/api/projects/${sourceId}/clips/${c.id}/download?kind=mp4`;
        a.download = "";
        document.body.appendChild(a);
        a.click();
        a.remove();
      }, i * 600);
    });
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Deine Clips</h1>
          <p className="mt-1 text-sm text-text-2">
            {clips.length === 1 ? "1 Clip" : `${clips.length} Clips`}
            {laufend > 0 ? ` · ${laufend} ${laufend === 1 ? "wird" : "werden"} noch gebaut` : " · alle fertig"}
            {stilName ? (
              <>
                {" · Stil "}
                {stilHref ? (
                  <a href={stilHref} className="text-text hover:underline">
                    {stilName}
                  </a>
                ) : (
                  stilName
                )}
              </>
            ) : null}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="ghost" onClick={() => setStilOffen((o) => !o)} aria-expanded={stilOffen}>
            Stil ändern
          </Button>
          <Button type="button" onClick={alleLaden} disabled={fertig.length === 0}>
            {fertig.length === clips.length ? "Alle herunterladen" : `${fertig.length} fertige herunterladen`}
          </Button>
        </div>
      </div>

      {stilOffen && (
        <StilWahl
          sourceId={sourceId}
          clips={clips}
          aktuell={aktuellerLook}
          onFertig={() => {
            setStilOffen(false);
            router.refresh();
          }}
        />
      )}

      {formate.size > 1 && (
        <div role="tablist" aria-label="Format" className="flex w-fit gap-1 rounded-pill border border-line p-1">
          {(
            [
              ["alle", "Alle"],
              ["9:16", "Hochformat"],
              ["16:9", "Querformat"],
            ] as [Filter, string][]
          ).map(([id, name]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={filter === id}
              onClick={() => setFilter(id)}
              className={cn(
                "transition-soft rounded-pill px-4 py-1.5 text-sm",
                filter === id ? "bg-white/10 text-text" : "text-text-2 hover:text-text",
              )}
            >
              {name}
            </button>
          ))}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
        {sortiert.map((clip, i) => (
          <ClipKarte
            key={clip.id}
            nr={i + 1}
            clip={clip}
            cand={clip.candidate_id ? byCand.get(clip.candidate_id) ?? null : null}
            sourceId={sourceId}
            mediaBase={mediaBase}
            demoSrc={demoSrc}
          />
        ))}
      </div>
    </div>
  );
}

function ClipKarte({
  nr,
  clip,
  cand,
  sourceId,
  mediaBase,
  demoSrc,
}: {
  nr: number;
  clip: Clip;
  cand: Candidate | null;
  sourceId: string;
  mediaBase: string | null;
  demoSrc: string | null;
}) {
  const fertig = clip.status === "rendered" || clip.status === "exported";
  const fehler = clip.status === "failed";
  const titel = clip.title_card || cand?.rubric?.suggested_title_card?.trim() || ersterSatz(cand?.rubric?.text) || `Clip ${nr}`;
  const laenge = clip.duration_s ?? (cand ? cand.end_s - cand.start_s : null);
  const eigene = mediaUrl(mediaBase, clip.file_key);
  /* Ohne eigene Datei (Testmodus) zeigt die Vorschau die Stelle im Beispielvideo. */
  const src = eigene ?? (demoSrc && cand ? `${demoSrc}#t=${cand.start_s.toFixed(1)},${cand.end_s.toFixed(1)}` : null);
  const poster = mediaUrl(mediaBase, clip.poster_key) ?? undefined;
  const hoch = clip.aspect === "9:16" || clip.aspect === "4:5";

  return (
    <GlassCard padding="sm" className="flex flex-col gap-3">
      <div className={cn("relative overflow-hidden rounded-inner bg-black", hoch ? "aspect-[9/16]" : "aspect-video")}>
        {fertig && src ? (
          <video src={src} poster={poster} controls playsInline preload="metadata" className="h-full w-full object-cover" />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-4 text-center">
            {fehler ? (
              <p className="text-sm text-attention">Dieser Clip ließ sich nicht bauen.</p>
            ) : (
              <>
                <span aria-hidden className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
                <p className="text-sm text-text-2">Wird gebaut</p>
              </>
            )}
          </div>
        )}
        <span className="absolute left-2 top-2 rounded-pill bg-black/70 px-2 py-0.5 text-xs text-text">
          {clip.aspect === "16:9" ? "Quer" : "Hoch"}
          {laenge ? ` · ${dauer(laenge)}` : ""}
        </span>
        {cand?.total != null && (
          <span
            className="absolute right-2 top-2 rounded-pill bg-black/70 px-2 py-0.5 text-xs font-medium text-text"
            title="Wie stark dieser Moment als Kurzvideo ist, von 0 bis 10"
          >
            {cand.total.toLocaleString("de-AT", { maximumFractionDigits: 1 })}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-1 px-1">
        <p className="line-clamp-2 font-medium text-text">{titel}</p>
        {cand?.why && <p className="line-clamp-2 text-sm text-text-2">{cand.why}</p>}
      </div>
      <div className="mt-auto flex flex-wrap gap-2 px-1 pb-1">
        {fertig ? (
          <>
            <a
              href={`/api/projects/${sourceId}/clips/${clip.id}/download?kind=mp4`}
              download
              className="transition-soft inline-flex h-9 items-center rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white"
            >
              Herunterladen
            </a>
            {clip.srt_key && (
              <a
                href={`/api/projects/${sourceId}/clips/${clip.id}/download?kind=srt`}
                download
                className="transition-soft inline-flex h-9 items-center rounded-pill border border-line px-4 text-sm text-text-2 hover:text-text"
              >
                Untertitel
              </a>
            )}
          </>
        ) : (
          <span className="inline-flex h-9 items-center text-sm text-text-3">{fehler ? "Wird neu versucht, wenn du den Stil änderst" : "Gleich fertig"}</span>
        )}
      </div>
    </GlassCard>
  );
}

/* Stil für alle Clips dieses Videos: ein Look, dann wird jeder Clip neu gebaut. Dieselben zehn
 * Looks wie unter „Stile". Der Stil der Kundenvorlage bleibt unberührt. */
function StilWahl({
  sourceId,
  clips,
  aktuell,
  onFertig,
}: {
  sourceId: string;
  clips: Clip[];
  aktuell: string | null;
  onFertig: () => void;
}) {
  const [wahl, setWahl] = useState<string | null>(aktuell);
  const [laeuft, setLaeuft] = useState(false);
  const [fehler, setFehler] = useState<string | null>(null);

  const anwenden = async () => {
    const look = LOOKS.find((l) => l.id === wahl);
    if (!look) return;
    setLaeuft(true);
    setFehler(null);
    let schief = 0;
    for (const c of clips) {
      if (c.status === "rendering" || c.status === "deleted") continue;
      try {
        const stil: CaptionStyle = look.stil;
        const r1 = await fetch(`/api/projects/${sourceId}/clips/${c.id}/caption-style`, {
          method: "PATCH",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ caption_style: stil }),
        });
        const r2 = r1.ok ? await fetch(`/api/projects/${sourceId}/clips/${c.id}/render`, { method: "POST" }) : r1;
        if (!r2.ok) schief++;
      } catch {
        schief++;
      }
    }
    setLaeuft(false);
    if (schief > 0) setFehler(`${schief} ${schief === 1 ? "Clip ließ" : "Clips ließen"} sich nicht neu bauen.`);
    else onFertig();
  };

  return (
    <GlassCard padding="md" className="flex flex-col gap-4">
      <div>
        <h2 className="text-lg font-medium">Stil für alle Clips</h2>
        <p className="mt-1 text-sm text-text-2">Wähle, wie die Untertitel aussehen. Alle Clips dieses Videos werden danach neu gebaut.</p>
      </div>
      <div role="radiogroup" aria-label="Stil" className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {LOOKS.map((l) => {
          const v = mitVorgabe(l.stil);
          const aktiv = wahl === l.id;
          return (
            <button
              key={l.id}
              type="button"
              role="radio"
              aria-checked={aktiv}
              onClick={() => setWahl(l.id)}
              disabled={laeuft}
              className={cn(
                "transition-soft flex min-w-0 flex-col items-start gap-1 rounded-inner border px-3 py-2.5 text-left disabled:opacity-60",
                aktiv ? "border-white/60 bg-white/10" : "border-line hover:border-line-strong",
              )}
            >
              <span
                aria-hidden
                className="text-lg leading-none text-text"
                style={{ fontFamily: `"${v.font}", Inter, sans-serif`, textTransform: v.all_caps ? "uppercase" : "none" }}
              >
                Aa
              </span>
              <span className={cn("text-sm font-medium", aktiv ? "text-text" : "text-text-2")}>{l.name}</span>
              <span className="w-full truncate text-xs text-text-3" title={l.hinweis}>
                {l.hinweis}
              </span>
            </button>
          );
        })}
      </div>
      {fehler && <p className="text-sm text-attention">{fehler}</p>}
      <div className="flex justify-end">
        <Button type="button" onClick={anwenden} disabled={!wahl || laeuft}>
          {laeuft ? "Wird angewendet" : "Auf alle Clips anwenden"}
        </Button>
      </div>
    </GlassCard>
  );
}
