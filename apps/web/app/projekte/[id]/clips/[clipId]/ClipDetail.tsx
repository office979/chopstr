"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { reclassify } from "@/lib/transcript/fillers";
import { ASPECT_LABELS, formatClipDuration } from "@/lib/clips/labels";
import type { Aspect, FilmstripMeta, RenderShot, TranscriptVersion, TranscriptWord, Zeitmarke } from "@/lib/repo/types";
import { Zeitleiste } from "./Zeitleiste";
import { ClipPreview } from "./ClipPreview";
import { LiveVorschau } from "./LiveVorschau";
import { ClipTextEditor } from "./ClipTextEditor";
import { CaptionStudio, type GespeicherteVorlage } from "./CaptionStudio";
import { passtZumRender, type CaptionStyle } from "@/lib/clips/caption-style";

interface Correction {
  old_text: string;
  new_text: string;
  add_to_vocab: boolean;
}

interface Props {
  sourceId: string;
  sourceTitle: string;
  aspect: Aspect;
  durationS: number | null;
  clipSrc: string | null;
  posterSrc: string | null;
  sourceSrc: string | null;
  clipStart: number;
  clipEnd: number | null;
  words: TranscriptWord[];
  wordFrom: number | null;
  wordTo: number | null;
  speakerNames: Record<string, string>;
  canEdit: boolean;
  captionStyle: CaptionStyle;
  captionPresets: GespeicherteVorlage[];
  clipId: string;
  /* Der ``captions``-Block des Renderplans: was im Bild wirklich eingebrannt ist. */
  gerenderteCaptions: Record<string, unknown> | null;
  srcW: number | null;
  srcH: number | null;
  outW: number;
  outH: number;
  filmstripSrc: string | null;
  filmstripMeta: FilmstripMeta | null;
  zeitmarken: Zeitmarke[];
  shots: RenderShot[];
  quelleBreite: number | null;
}

/* Ein Clip: oben Vorschau, daneben sein Text. Gespeichert wird mit einem Klick, ohne Rückfrage.
 * Die Rückfrage kommt nur beim Zurückgehen mit offenen Änderungen. */
export function ClipDetail({
  sourceId,
  sourceTitle,
  aspect,
  durationS,
  clipSrc,
  posterSrc,
  sourceSrc,
  clipStart,
  clipEnd,
  words: initialWords,
  wordFrom,
  wordTo,
  speakerNames,
  canEdit,
  captionStyle,
  captionPresets,
  clipId,
  gerenderteCaptions,
  srcW,
  srcH,
  outW,
  outH,
  filmstripSrc,
  filmstripMeta,
  zeitmarken: markenAnfang,
  shots,
  quelleBreite,
}: Props) {
  const router = useRouter();
  const backHref = `/projekte/${sourceId}/clips`;

  const [original, setOriginal] = useState<TranscriptWord[]>(initialWords);
  const [words, setWords] = useState<TranscriptWord[]>(initialWords);
  const [corrections, setCorrections] = useState<Map<number, Correction>>(new Map());
  const [currentTime, setCurrentTime] = useState(clipStart);
  const [seekTo, setSeekTo] = useState<{ at: number; nonce: number } | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [leaveOpen, setLeaveOpen] = useState(false);

  /* Untertitel: eigener Stand, eigener Speicherknopf. Bewusst getrennt vom Text, denn es sind zwei
   * verschiedene Entscheidungen, und der Text schreibt das Transkript des ganzen Videos um. */
  const [stil, setStil] = useState<CaptionStyle>(captionStyle);
  const [stilGespeichert, setStilGespeichert] = useState<CaptionStyle>(captionStyle);
  const [stilSaving, setStilSaving] = useState(false);
  const [vorlagen, setVorlagen] = useState<GespeicherteVorlage[]>(captionPresets);

  /* Zeitleiste: die Marken liegen hier, weil die Vorschau oben und die Leiste unten dieselben
   * brauchen. Gespeichert wird sofort beim Setzen, nicht ueber einen zweiten Knopf: eine Marke ist
   * eine einzelne kleine Entscheidung, und wer sie trifft, will nicht danach noch speichern. */
  const [marken, setMarken] = useState<Zeitmarke[]>(markenAnfang);
  /* Vorschau aus der Quelle (zeigt jede Aenderung sofort) oder das gebaute Video (zeigt das
   * Ergebnis des letzten Laufs). Voreingestellt ist die Vorschau: wer hier ist, stellt etwas ein. */
  const [zeigeGebautes, setZeigeGebautes] = useState(false);

  const hasText = wordFrom != null && wordTo != null && wordTo >= wordFrom;

  /* Nur die Wörter dieses Clips. Die Vorschau soll zeigen, was im Clip steht, nicht das ganze Video. */
  const clipWords = useMemo(
    () => (hasText ? words.slice(wordFrom, wordTo + 1) : []),
    [hasText, words, wordFrom, wordTo],
  );
  const laengstesWort = useMemo(
    () => clipWords.reduce((lang, w) => (w.text.length > lang.length ? w.text : lang), ""),
    [clipWords],
  );
  const stilGeaendert = useMemo(
    () => JSON.stringify(stil) !== JSON.stringify(stilGespeichert),
    [stil, stilGespeichert],
  );
  /* Zeigt das Video noch die Untertitel, die jetzt eingestellt sind? Verglichen wird gegen den
   * Renderplan und nicht gegen den gespeicherten Stand: nach dem Speichern ist nichts mehr
   * „geaendert", im Bild stehen aber weiter die alten. */
  const captionsVeraltet = useMemo(
    () => Boolean(clipSrc) && zeigeGebautes && !passtZumRender(stil, gerenderteCaptions),
    [clipSrc, zeigeGebautes, stil, gerenderteCaptions],
  );

  /* Liegt der fertige Clip vor, läuft er selbst. Sonst läuft das ganze Video und bleibt am Ende
   * der Stelle stehen. Fest im Speicher, sonst hinge der Effekt im Player an jedem Zeitschritt. */
  const trim = useMemo(() => (clipSrc ? null : { start: clipStart, end: clipEnd }), [clipSrc, clipStart, clipEnd]);

  const speakers = useMemo(() => {
    const seen = new Set<string>();
    for (const w of initialWords) seen.add(w.speaker);
    return [...seen].sort();
  }, [initialWords]);

  /* Geändert ist, was im Bereich dieses Clips vom gespeicherten Stand abweicht. */
  const dirty = useMemo(() => {
    if (!hasText) return false;
    for (let i = wordFrom; i <= wordTo; i += 1) {
      const a = words[i];
      const b = original[i];
      if (!a || !b) continue;
      if (a.text !== b.text || a.speaker !== b.speaker) return true;
    }
    return false;
  }, [hasText, wordFrom, wordTo, words, original]);

  const editWord = useCallback(
    (index: number, raw: string) => {
      const text = raw.trim();
      if (!text) return;
      setWords((prev) => {
        if (!prev[index] || prev[index].text === text) return prev;
        const next = [...prev];
        next[index] = reclassify(prev[index], text);
        return next;
      });
      setCorrections((prev) => {
        const next = new Map(prev);
        const before = original[index];
        if (!before || before.text === text) next.delete(index);
        else next.set(index, { old_text: before.text, new_text: text, add_to_vocab: false });
        return next;
      });
    },
    [original],
  );

  const changeSpeaker = useCallback((indices: number[], speaker: string) => {
    setWords((prev) => {
      const next = [...prev];
      for (const i of indices) {
        if (next[i] && next[i].speaker !== speaker) next[i] = { ...next[i], speaker };
      }
      return next;
    });
  }, []);

  const seek = useCallback((at: number) => {
    setSeekTo({ at, nonce: Date.now() });
    setCurrentTime(at);
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/transcript`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          words,
          corrections: [...corrections.entries()].map(([word_index, c]) => ({ word_index, ...c })),
          /* Die Namen der Sprecher bleiben, wie sie sind. Ohne sie wären sie nach dem Speichern weg. */
          speaker_names: speakerNames,
        }),
      });
      const data = (await res.json()) as { error?: string; version?: TranscriptVersion };
      if (!res.ok || !data.version) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
      setOriginal(words);
      setCorrections(new Map());
      setMessage({ tone: "ok", text: "Gespeichert." });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt. Versuch es noch einmal.",
      });
    } finally {
      setSaving(false);
    }
  };

  const stilSpeichern = async () => {
    setStilSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/caption-style`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ caption_style: stil }),
      });
      const data = (await res.json()) as { error?: string; caption_style?: CaptionStyle; needs_render?: boolean };
      if (!res.ok) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
      const gesichert = data.caption_style ?? stil;
      setStil(gesichert);
      setStilGespeichert(gesichert);
      setMessage({
        tone: "ok",
        text: data.needs_render
          ? "Untertitel gespeichert. Sie erscheinen, sobald der Clip neu gebaut wird."
          : "Untertitel gespeichert.",
      });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt" });
    } finally {
      setStilSaving(false);
    }
  };

  const markenSichern = useCallback(
    async (naechste: Zeitmarke[]) => {
      setMarken(naechste);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/zeitmarken`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ zeitmarken: naechste }),
        });
        const data = (await res.json()) as { error?: string; zeitmarken?: Zeitmarke[]; needs_render?: boolean };
        if (!res.ok) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
        if (data.zeitmarken) setMarken(data.zeitmarken);
        setMessage({
          tone: "ok",
          text: data.needs_render ? "Gespeichert. Wirkt, sobald der Clip neu gebaut wird." : "Gespeichert.",
        });
      } catch (err) {
        setMarken(marken);
        setMessage({ tone: "error", text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt" });
      }
    },
    [sourceId, clipId, marken],
  );

  const goBack = () => {
    if (dirty || stilGeaendert) setLeaveOpen(true);
    else router.push(backHref);
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          {/* Ein Pfeil, ein Weg zurück. Kein zweiter Knopf, der wieder in die Tiefe führt. */}
          <button
            type="button"
            onClick={goBack}
            aria-label="Zurück zu den Clips"
            className="transition-soft mt-1 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full border border-line text-text-2 hover:border-line-strong hover:text-text"
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M9.5 3.5L5 8l4.5 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <div>
            <p className="text-sm text-text-2">{sourceTitle}</p>
            <h1 className="text-2xl font-semibold tracking-[var(--tracking-display)] sm:text-3xl">Clip</h1>
            <p className="mt-1 text-sm text-text-2">
              {ASPECT_LABELS[aspect]}, {formatClipDuration(durationS)}
            </p>
          </div>
        </div>
        <ButtonLink href={`/projekte/${sourceId}/transkript`} variant="ghost" size="sm">
          Transkript anzeigen
        </ButtonLink>
      </div>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,420px)_minmax(0,1fr)] lg:items-start">
        <div className="lg:sticky lg:top-8">
          {clipSrc && (
            <div className="mb-3 flex gap-1 rounded-pill border border-line p-1">
              {[
                { an: false, name: "Vorschau", titel: "Zeigt, was jetzt eingestellt ist" },
                { an: true, name: "Gebautes Video", titel: "Das Ergebnis des letzten Bauens" },
              ].map((w) => (
                <button
                  key={w.name}
                  type="button"
                  title={w.titel}
                  onClick={() => setZeigeGebautes(w.an)}
                  aria-pressed={zeigeGebautes === w.an}
                  className={cn(
                    "transition-soft flex-1 rounded-pill px-3 py-1.5 text-sm",
                    zeigeGebautes === w.an ? "bg-white/10 text-text" : "text-text-2 hover:text-text",
                  )}
                >
                  {w.name}
                </button>
              ))}
            </div>
          )}

          {clipSrc && zeigeGebautes ? (
            <ClipPreview
            src={clipSrc ?? sourceSrc}
            posterSrc={posterSrc}
            aspect={aspect}
            /* Der fertige Clip beginnt bei null, das ganze Video läuft in seiner eigenen Zeit. */
            timeOffset={clipSrc ? clipStart : 0}
            trim={trim}
            onTime={setCurrentTime}
            seekTo={seekTo}
            /* Die Vorschau der Untertitel NUR, solange das Quellvideo laeuft. Im fertigen Clip sind
             * sie eingebrannt; beides zugleich ergibt zwei Texte uebereinander. */
            overlay={null}
            />
          ) : (
            <LiveVorschau
              src={sourceSrc}
              posterSrc={posterSrc}
              aspect={aspect}
              srcW={srcW}
              srcH={srcH}
              outW={outW}
              outH={outH}
              clipStart={clipStart}
              clipEnd={clipEnd}
              zeit={currentTime}
              onTime={setCurrentTime}
              seekTo={seekTo}
              shots={shots}
              zeitmarken={marken}
              stil={stil}
              woerter={clipWords}
            />
          )}

          {/* Im fertigen Clip sind die Untertitel eingebrannt. Wer den Stil danach aendert, sieht
            * im Bild weiter die alten - das muss dastehen, sonst wirkt es, als sei nichts passiert. */}
          {captionsVeraltet && (
            <p className="mt-3 text-sm text-attention">
              Im Bild sind noch die alten Untertitel. Neu bauen, um die neuen zu sehen.
            </p>
          )}

          <div className="mt-4">
            <Zeitleiste
              filmstripSrc={filmstripSrc}
              filmstripMeta={filmstripMeta}
              videoSrc={sourceSrc}
              clipStart={clipStart}
              dauerS={durationS ?? (clipEnd != null ? clipEnd - clipStart : 0)}
              zeit={currentTime}
              onSeek={seek}
              shots={shots}
              zeitmarken={marken}
              onMarke={(m) => void markenSichern([...marken.filter((x) => Math.abs(x.ab_s - m.ab_s) > 0.35), m].sort((a, b) => a.ab_s - b.ab_s))}
              onMarkeWeg={(abS) => void markenSichern(marken.filter((x) => x.ab_s !== abS))}
              quelleBreite={quelleBreite}
              canEdit={canEdit}
            />
          </div>
        </div>

        <div className="flex flex-col gap-5">
          {hasText ? (
            <ClipTextEditor
              words={words}
              original={original}
              wordFrom={wordFrom}
              wordTo={wordTo}
              speakers={speakers}
              speakerNames={speakerNames}
              currentTime={currentTime}
              canEdit={canEdit}
              onEditWord={editWord}
              onChangeSpeaker={changeSpeaker}
              onSeek={seek}
            />
          ) : (
            <GlassCard padding="md">
              <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
            </GlassCard>
          )}

          <CaptionStudio
            stil={stil}
            onChange={setStil}
            vorlagen={vorlagen}
            onVorlagenChange={setVorlagen}
            laengstesWort={laengstesWort}
            canEdit={canEdit}
            gespeichert={!stilGeaendert}
            speichern={() => void stilSpeichern()}
            zuruecksetzen={() => setStil({})}
            saving={stilSaving}
          />

          {canEdit && hasText && (
            <GlassCard padding="md" selected={dirty}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-text-2">
                  {dirty ? "Du hast etwas geändert." : "Nichts geändert."}
                </p>
                <Button variant={dirty ? "primary" : "ghost"} disabled={!dirty || saving} onClick={save}>
                  {saving ? "Wird gespeichert" : "Speichern"}
                </Button>
              </div>
              {message && (
                <p
                  role="status"
                  aria-live="polite"
                  className={cn("mt-3 text-sm", message.tone === "ok" ? "text-text" : "text-attention")}
                >
                  {message.text}
                </p>
              )}
            </GlassCard>
          )}
        </div>
      </div>

      <Modal
        open={leaveOpen}
        onClose={() => setLeaveOpen(false)}
        title="Willst du die Seite wirklich verlassen?"
        description="Du hast etwas geändert und noch nicht gespeichert. Wenn du jetzt gehst, ist die Änderung weg."
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setLeaveOpen(false)}>
            Hier bleiben
          </Button>
          <Button variant="danger" onClick={() => router.push(backHref)}>
            Ohne Speichern verlassen
          </Button>
        </div>
      </Modal>
    </>
  );
}
