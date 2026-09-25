"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { GlassCard } from "@/components/ui/GlassCard";
import { Button, ButtonLink } from "@/components/ui/Button";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { reclassify } from "@/lib/transcript/fillers";
import { ASPECT_LABELS, formatClipDuration } from "@/lib/clips/labels";
import type { Aspect, ClipStatus, RenderPlan, RenderShot, TranscriptVersion, TranscriptWord, Zeitmarke } from "@/lib/repo/types";
import { VorschauStatus } from "./VorschauStatus";
import { Bildausschnitt, beschreibung as markeBeschreibung } from "./Bildausschnitt";
import { Timeline, luecken } from "./timeline/Timeline";
import { useFilmstreifen } from "./useFilmstreifen";
import type { WellenformDaten, WellenformStand } from "./timeline/Wellenform";
import {
  dauer as schnittDauer,
  gleich as schnittGleich,
  zusammenziehen,
  type Schnitt,
} from "@/lib/clips/schnitt";
import { pruefen } from "@/lib/clips/untertitel-pruefung";
import { vorschauStand } from "@/lib/clips/vorschau-stand";
import type { Befund } from "@/lib/clips/pruefstand";
import { fassungSatz, type Fassung } from "@/lib/brand/fassung";
import { ClipPreview } from "./ClipPreview";
import { LiveVorschau } from "./LiveVorschau";
import { ClipTextEditor } from "./ClipTextEditor";
import { CaptionStudio, type GespeicherteVorlage } from "./CaptionStudio";
import type { CaptionStyle } from "@/lib/clips/caption-style";

/* Eine Fassung im Verlauf: Schnitt und Marken gehoeren zusammen, weil „Rueckgaengig" den
 * letzten Schritt meint und nicht den letzten Schritt einer bestimmten Sorte. */
interface Stand {
  schnitt: Schnitt;
  marken: Zeitmarke[];
}

function markenGleich(a: Zeitmarke[], b: Zeitmarke[]): boolean {
  if (a.length !== b.length) return false;
  return a.every((m, i) => JSON.stringify(m) === JSON.stringify(b[i]));
}

interface Correction {
  old_text: string;
  new_text: string;
  add_to_vocab: boolean;
}

interface Props {
  sourceId: string;
  sourceTitle: string;
  /* Alle Clips dieses Videos in Reihenfolge, für „voriger/nächster Clip". */
  geschwister: string[];
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
  sprechertrennung: "done" | "skipped" | null;
  canEdit: boolean;
  captionStyle: CaptionStyle;
  captionPresets: GespeicherteVorlage[];
  clipId: string;
  srcW: number | null;
  srcH: number | null;
  outW: number;
  outH: number;
  zeitmarken: Zeitmarke[];
  shots: RenderShot[];
  quelleBreite: number | null;
  /* Der gespeicherte Schnitt: welche Abschnitte der Quelle dieser Clip zeigt. */
  komposition: Schnitt;
  /* Der Schnitt, der im gebauten Video steckt. Weicht er vom gespeicherten ab, zeigt das Video
   * ein altes Ergebnis, und das muss dastehen. */
  gerenderteSegmente: Schnitt | null;
  quelleDauerS: number;
  wellenformSrc: string | null;
  /* Ist das Video fertig analysiert? Ohne das lässt sich nicht sagen, ob eine fehlende Tonspur
   * noch kommt oder nie kommen wird. */
  quelleFertig: boolean;
  /* Mit welcher Fassung der Marke wurde dieses Video geclippt? Null, wenn keine Marke zugeordnet
   * ist. */
  markenFassung: Fassung | null;
  markenName: string | null;
  /* Die Farben dieser Marke, als schnelle Wahl bei den Untertiteln. Eine Agentur soll die
   * Kundenfarbe nicht bei jedem Clip aus einem Farbrad suchen. */
  markenFarben: string[];
  /* Was an diesem Clip auffällt: ein Schnitt, der den Sinn verändert, ein Marker aus der Analyse
   * („muss als Werbung gekennzeichnet werden"), ein Befund der technischen Prüfung. Gerechnet auf
   * dem Server, siehe page.tsx. */
  befunde: Befund[];
  /* Der Plan des letzten Laufs: daran hängt, ob das gebaute Video noch aktuell ist. */
  renderPlan: RenderPlan | null;
  clipStatus: ClipStatus;
  renderFehler: string | null;
  transkriptVersion: number | null;
  /* Ohne Markenprofil gibt es kein Wörterbuch, in das eine Schreibweise wandern könnte. */
  markeVorhanden: boolean;
  /* Die Schriften, für die in dieser Installation wirklich eine Datei vorliegt. */
  schriftenVorhanden: string[];
}

/* Ein Clip: oben Vorschau, daneben sein Text. Gespeichert wird mit einem Klick, ohne Rückfrage.
 * Die Rückfrage kommt nur beim Zurückgehen mit offenen Änderungen. */
/* Die vier Arbeitsbereiche eines Clips.
 *
 * Vier und nicht acht: mehr Reiter beantworten die Frage „wo mache ich das?" nicht besser,
 * sondern verlagern sie nur. Die Reihenfolge ist die des Arbeitens - erst der Schnitt, dann der
 * Text, dann das Aussehen, zuletzt das Fertigmachen. */
export type Bereich = "schnitt" | "text" | "untertitel" | "fertig";

const BEREICHE: { id: Bereich; name: string; satz: string }[] = [
  { id: "schnitt", name: "Schnitt", satz: "Timeline und Bildausschnitt" },
  { id: "text", name: "Text", satz: "Gesprochene Wörter prüfen" },
  { id: "untertitel", name: "Untertitel", satz: "Aussehen, Position, Lesbarkeit" },
  { id: "fertig", name: "Fertigstellen", satz: "Offenes prüfen, clippen, herunterladen" },
];

export function ClipDetail({
  sourceId,
  sourceTitle,
  geschwister,
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
  sprechertrennung,
  canEdit,
  captionStyle,
  captionPresets,
  clipId,
  srcW,
  srcH,
  outW,
  outH,
  zeitmarken: markenAnfang,
  shots,
  quelleBreite,
  komposition,
  gerenderteSegmente,
  quelleDauerS,
  wellenformSrc,
  quelleFertig,
  markenFassung,
  markenName,
  markenFarben,
  befunde,
  renderPlan,
  clipStatus,
  renderFehler,
  transkriptVersion,
  markeVorhanden,
  schriftenVorhanden,
}: Props) {
  const router = useRouter();
  const backHref = `/projekte/${sourceId}/clips`;

  const [original, setOriginal] = useState<TranscriptWord[]>(initialWords);
  const [words, setWords] = useState<TranscriptWord[]>(initialWords);
  const [corrections, setCorrections] = useState<Map<number, Correction>>(new Map());
  const [currentTime, setCurrentTime] = useState(clipStart);
  const [seekTo, setSeekTo] = useState<{ at: number; nonce: number } | null>(null);
  const [saving, setSaving] = useState(false);
  /* Bei einem Fehler steht in ``nochmal``, was zu wiederholen ist. Eine Meldung ohne Weg zurueck
   * laesst den Nutzer mit seiner Arbeit im Browser sitzen und sonst nichts. */
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; nochmal?: () => void } | null>(null);
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
  /* Welcher Arbeitsbereich offen ist.
   *
   * Vorher lag alles untereinander auf einer Seite: Vorschau und Timeline oben, darunter Text,
   * Untertitel und Bildausschnitt. Wer einen Regler weiter unten anfasste, sah die Wirkung nicht,
   * weil das Video zwei Bildschirme weiter oben stand. Jetzt bleibt das Video stehen und nur der
   * rechte Teil wechselt.
   *
   * Alle vier Bereiche bleiben im Baum und werden nur ausgeblendet. Das ist der Grund, warum ein
   * Wechsel nichts zurücksetzt: nicht gespeicherte Eingaben, die gewählte Stelle und die
   * Abspielposition überleben, weil nichts neu aufgebaut wird. */
  const [bereich, setBereich] = useState<Bereich>("schnitt");

  /* Der Verlauf fuer Rueckgaengig und Wiederherstellen. Eine Fassung ist Schnitt UND Marken
   * zusammen: wer einen Marker verschiebt und dann „Rueckgaengig" drueckt, meint den Marker.
   * Zwei Listen alter Fassungen reichen; ein Diff waere Aufwand ohne Nutzen, sie sind winzig. */
  const [schnitt, setSchnitt] = useState<Schnitt>(komposition);
  const [gesichert, setGesichert] = useState<Schnitt>(komposition);
  const [zurueckStapel, setZurueckStapel] = useState<Stand[]>([]);
  const [vorStapel, setVorStapel] = useState<Stand[]>([]);
  const [schnittSaving, setSchnittSaving] = useState(false);
  const [wellenform, setWellenform] = useState<WellenformDaten | null>(null);
  /* Warum es (noch) keine Tonspur gibt: „wird noch erzeugt" ist etwas anderes als „liess sich
   * nicht laden", und der Nutzer soll den Unterschied sehen. */
  const [wellenformStand, setWellenformStand] = useState<WellenformStand>(
    wellenformSrc ? "laeuft" : quelleFertig ? "keine" : "fehlt",
  );
  const [laeuft, setLaeuft] = useState(false);
  const [spielen, setSpielen] = useState(0);

  useEffect(() => {
    if (!wellenformSrc) {
      /* Fertig verarbeitet und trotzdem keine Tonspur: dann kommt auch keine mehr. Der alte Satz
       * „Sie entsteht beim Verarbeiten" stand genau an diesen Videos und versprach etwas, worauf
       * man beliebig lange warten konnte. */
      setWellenformStand(quelleFertig ? "keine" : "fehlt");
      return undefined;
    }
    let weg = false;
    setWellenformStand("laeuft");
    fetch(wellenformSrc)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (weg) return;
        if (d && Array.isArray(d.werte)) {
          setWellenform(d as WellenformDaten);
          setWellenformStand("da");
        } else {
          setWellenformStand("fehler");
        }
      })
      .catch(() => {
        if (!weg) setWellenformStand("fehler");
      });
    return () => {
      weg = true;
    };
  }, [wellenformSrc, quelleFertig]);

  /* Der jeweils neueste Stand, auch mitten in einem Ziehen. Die Zustandsvariablen selbst taugen
   * dafuer nicht: waehrend eines Zugs kommen Dutzende Ereignisse, bevor React neu zeichnet. */
  const schnittRef = useRef(schnitt);
  useEffect(() => {
    schnittRef.current = schnitt;
  }, [schnitt]);
  const markenRef = useRef(marken);
  useEffect(() => {
    markenRef.current = marken;
  }, [marken]);

  /* Die Marken, solange jemand an einem Regler zieht - und nur dafür.
   *
   * Sie liegen bewusst NICHT in ``marken``: ein Effekt spiegelt diesen Zustand nach
   * ``markenRef``, und ``markenRef`` ist die Grundlage für Speichern und Rückgängig. Ein erster
   * Versuch führte die Vorschau über ``marken``, und danach hielt das Speichern den gezogenen
   * Wert für den schon gespeicherten - es passierte nichts, ohne jede Meldung. */
  const [markenVorschau, setMarkenVorschau] = useState<Zeitmarke[] | null>(null);
  /* Was die Anzeige zeigt: beim Ziehen die Vorschau, sonst der gespeicherte Stand. */
  const markenSicht = markenVorschau ?? marken;

  const standJetzt = useCallback((): Stand => ({ schnitt: schnittRef.current, marken: markenRef.current }), []);
  const merken = useCallback(
    (stand: Stand) => {
      setZurueckStapel((z) => [...z.slice(-29), stand]);
      setVorStapel([]);
    },
    [],
  );

  /* Hier wird bewusst NICHT aufgeraeumt: aufraeumen zieht beruehrende Abschnitte zusammen, und
   * genau die entstehen beim Teilen. Die einzelnen Schritte raeumen selbst auf, soweit noetig.
   * Beim Bauen werden durchgehende Abschnitte wieder zusammengefasst (render_plan), damit an
   * einer Naht ohne entfernten Teil keine Tonblende hoerbar wird. */
  const schnittSetzen = useCallback(
    (neu: Schnitt) => {
      if (!neu.length || schnittGleich(neu, schnittRef.current)) return;
      merken(standJetzt());
      schnittRef.current = neu;
      setSchnitt(neu);
    },
    [merken, standJetzt],
  );

  /* Ziehen an einer Kante: waehrend des Zugs nur anzeigen. Sonst stuende nach einem einzigen
   * Zug fuer jede Mausbewegung eine Fassung im Verlauf, und „Rueckgaengig" ginge einen
   * Bildpunkt zurueck statt einen Schritt. */
  const zugStart = useRef<Stand | null>(null);
  const schnittZiehen = useCallback(
    (neu: Schnitt) => {
      if (!neu.length) return;
      if (!zugStart.current) zugStart.current = standJetzt();
      schnittRef.current = neu;
      setSchnitt(neu);
    },
    [standJetzt],
  );
  const schnittLoslassen = useCallback(() => {
    const start = zugStart.current;
    zugStart.current = null;
    if (!start || schnittGleich(start.schnitt, schnittRef.current)) return;
    merken(start);
  }, [merken]);

  /* Marken speichern, ohne den Verlauf anzufassen. Gerechnet wird immer vom neuesten Stand aus:
   * ohne das rechnet ein zweiter Klick, der vor der Antwort des ersten kommt, mit einer alten
   * Liste weiter, und aus einer verschobenen Marke werden zwei. */
  /* Benannter Funktionsausdruck, damit der Wiederholen-Knopf denselben Aufruf noch einmal machen
   * kann, ohne sich auf eine Variable von aussen zu beziehen. */
  const markenSpeichern = useCallback(
    async function speichern(naechste: Zeitmarke[]): Promise<void> {
      const vorher = markenRef.current;
      markenRef.current = naechste;
      setMarken(naechste);
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/zeitmarken`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ zeitmarken: naechste }),
        });
        const data = (await res.json()) as { error?: string; zeitmarken?: Zeitmarke[]; needs_render?: boolean };
        if (!res.ok) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
        if (data.zeitmarken) {
          markenRef.current = data.zeitmarken;
          setMarken(data.zeitmarken);
        }
        setMessage({
          tone: "ok",
          text: data.needs_render ? "Gespeichert. Wirkt, sobald das Video neu geclippt wird." : "Gespeichert.",
        });
      } catch (err) {
        markenRef.current = vorher;
        setMarken(vorher);
        setMessage({
          tone: "error",
          text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt",
          nochmal: () => void speichern(naechste),
        });
      }
    },
    [sourceId, clipId],
  );

  /* Eine Fassung wiederherstellen. Der Schnitt liegt nur hier, die Marken liegen auch auf dem
   * Server: weichen sie ab, werden sie mitgespeichert, sonst zeigte die Seite nach dem Neuladen
   * wieder den alten Stand. */
  const standSetzen = useCallback(
    (stand: Stand) => {
      schnittRef.current = stand.schnitt;
      setSchnitt(stand.schnitt);
      if (!markenGleich(stand.marken, markenRef.current)) void markenSpeichern(stand.marken);
    },
    [markenSpeichern],
  );

  /* Bewusst ausserhalb der Aktualisierungsfunktionen gerechnet: setState darf nur den neuen
   * Wert liefern. Ein Speichern von dort aus liefe im Entwicklungsmodus zweimal. */
  const zurueck = useCallback(() => {
    const letzte = zurueckStapel[zurueckStapel.length - 1];
    if (!letzte) return;
    const jetzt = standJetzt();
    setZurueckStapel((z) => z.slice(0, -1));
    setVorStapel((v) => [...v, jetzt]);
    standSetzen(letzte);
  }, [zurueckStapel, standJetzt, standSetzen]);

  const vor = useCallback(() => {
    const naechste = vorStapel[vorStapel.length - 1];
    if (!naechste) return;
    const jetzt = standJetzt();
    setVorStapel((v) => v.slice(0, -1));
    setZurueckStapel((z) => [...z, jetzt]);
    standSetzen(naechste);
  }, [vorStapel, standJetzt, standSetzen]);

  const schnittGeaendert = !schnittGleich(schnitt, gesichert);
  /* Verglichen wird in der Form, die auch im Plan steht: der Renderer zieht durchgehende
   * Abschnitte zusammen. Ohne das gaelte ein geteilter, frisch gebauter Clip fuer immer als
   * veraltet. */
  const schnittVeraltet =
    Boolean(clipSrc) &&
    gerenderteSegmente != null &&
    !schnittGleich(zusammenziehen(gesichert), zusammenziehen(gerenderteSegmente));
  const neueDauer = schnittDauer(schnitt);

  /* Zeigt das gebaute Video noch, was eingestellt ist? Dieselbe Rechnung wie im Renderstand, hier
   * gebraucht, um es direkt am Umschalter zu sagen: wer auf „Zuletzt gebaut" klickt, soll dort
   * erfahren, dass er eine alte Fassung sieht, und nicht erst weiter unten. */
  const gebautesVeraltet =
    Boolean(clipSrc) &&
    vorschauStand({
      status: clipStatus,
      hatDatei: Boolean(clipSrc),
      plan: renderPlan,
      renderFehler,
      transkriptVersion,
      stil: stilGespeichert,
      schnitt: gesichert,
      zeitmarken: marken,
    }) === "veraltet";

  /* Der Zeitraum, den die Timeline zeigt: der geladene Schnitt plus zehn Sekunden Luft auf beiden
   * Seiten, damit sich der Anfang auch wieder verlaengern laesst. Bewusst fest ab dem Laden und
   * NICHT dem laufenden Schnitt folgend: sonst verschoebe sich die Zeitskala unter der Hand,
   * waehrend jemand an einer Kante zieht. */
  const bereichVon = useMemo(() => Math.max(0, (komposition[0]?.start ?? 0) - 10), [komposition]);
  const bereichBis = useMemo(
    () => Math.min(quelleDauerS || Infinity, (komposition[komposition.length - 1]?.end ?? 0) + 10),
    [komposition, quelleDauerS],
  );
  /* Die Einzelbilder fuer die Bildspur. Sie haengen am festen Bereich, nicht am Schnitt: sonst
   * wuerde der Streifen bei jeder Kante neu gezeichnet. */
  const streifenBilder = useFilmstreifen(sourceSrc, bereichVon, bereichBis);

  /* Anfang und Ende des Clips nach dem aktuellen Schnitt. Daran haengt die Vorschau: sie soll das
   * zeigen, was gerade eingestellt ist, nicht den Stand vom Laden. */
  const vorschauStart = schnitt[0]?.start ?? clipStart;
  const vorschauEnde = schnitt[schnitt.length - 1]?.end ?? clipEnd;
  /* Die entfernten Teile. Beim Abspielen springt die Vorschau darueber hinweg, damit sie denselben
   * Ablauf zeigt wie der spaetere Clip. */
  const vorschauLuecken = useMemo(() => luecken(schnitt, vorschauStart, vorschauEnde ?? vorschauStart), [schnitt, vorschauStart, vorschauEnde]);

  const auswahlAusShots = useMemo(
    () => [...new Set(shots.flatMap((sh) => sh.auswahl ?? []))].sort((a, b) => a - b),
    [shots],
  );

  const hasText = wordFrom != null && wordTo != null && wordTo >= wordFrom;

  /* Nur die Wörter dieses Clips. Die Vorschau soll zeigen, was im Clip steht, nicht das ganze Video. */
  const clipWords = useMemo(
    () => (hasText ? words.slice(wordFrom, wordTo + 1) : []),
    [hasText, words, wordFrom, wordTo],
  );
  /* Untertitel, die über den sicheren Bereich hinausragen. Gerechnet auf den EINGESTELLTEN Stil,
   * weil die Frage „kann ich jetzt bauen?" sich auf das bezieht, was gleich gebaut wird. */
  const offeneUntertitel = useMemo(
    () => pruefen(clipWords, stil).filter((b) => b.grund === "passt_nicht").length,
    [clipWords, stil],
  );

  const stilGeaendert = useMemo(
    () => JSON.stringify(stil) !== JSON.stringify(stilGespeichert),
    [stil, stilGespeichert],
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

  /* Ein Wort für die ganze Seite: gibt es irgendwo etwas Ungespeichertes? Steht in der Kopfzeile
   * und entscheidet, ob das Bauen gesperrt ist. */
  const offeneAenderungen = dirty || stilGeaendert || schnittGeaendert;
  /* Was genau offen ist. „Du hast etwas geändert" lässt den Nutzer raten, was er verliert. */
  const offeneListe = [
    schnittGeaendert ? "der Schnitt" : null,
    dirty ? "der Text" : null,
    stilGeaendert ? "die Untertitel" : null,
  ]
    .filter(Boolean)
    .join(", ") || "nichts";

  const editWord = useCallback(
    (index: number, raw: string, merken = false) => {
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
        /* ``add_to_vocab`` traegt die Schreibweise ins Woerterbuch der Marke. Das entscheidet der
         * Nutzer je Wort: ein Eigenname gehoert dorthin, ein Tippfehler nicht. */
        else next.set(index, { old_text: before.text, new_text: text, add_to_vocab: merken });
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

  /* Kommt jemand über „Zur Stelle bei 0:12" aus einer Kundenrückmeldung, steht die Sekunde in
   * der Adresse - und zwar im FERTIGEN CLIP gezählt, denn nur den hat der Kunde gesehen. Hier
   * wird sie in die Quellzeit umgerechnet, in der Vorschau und Timeline rechnen. */
  useEffect(() => {
    const roh = new URLSearchParams(window.location.search).get("bei");
    const imClip = roh == null ? NaN : Number(roh);
    if (!Number.isFinite(imClip) || imClip < 0) return;
    const ziel = clipStart + imClip;
    setSeekTo({ at: ziel, nonce: Date.now() });
    setCurrentTime(ziel);
    /* Nur beim Öffnen. Danach gehört die Abspielposition dem Nutzer. */
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt.",
        nochmal: () => void save(),
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
          ? "Untertitel gespeichert. Sie erscheinen, sobald das Video neu geclippt wird."
          : "Untertitel gespeichert.",
      });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt",
        nochmal: () => void stilSpeichern(),
      });
    } finally {
      setStilSaving(false);
    }
  };

  /* Eine Marke aendern: erst die bisherige Fassung in den Verlauf, dann speichern. */
  const markenAendern = useCallback(
    (rechnen: (vorher: Zeitmarke[]) => Zeitmarke[]) => {
      const naechste = rechnen(markenRef.current);
      if (markenGleich(naechste, markenRef.current)) return;
      merken(standJetzt());
      void markenSpeichern(naechste);
    },
    [merken, standJetzt, markenSpeichern],
  );

  const schnittSichern = async () => {
    setSchnittSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/schnitt`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ composition: schnitt }),
      });
      const data = (await res.json()) as { error?: string; composition?: Schnitt; needs_render?: boolean };
      if (!res.ok || !data.composition) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
      setSchnitt(data.composition);
      setGesichert(data.composition);
      setMessage({
        tone: "ok",
        text: data.needs_render ? "Schnitt gespeichert. Das Video muss neu geclippt werden." : "Schnitt gespeichert.",
      });
    } catch (err) {
      setMessage({
        tone: "error",
        text: err instanceof Error ? err.message : "Das Speichern hat nicht geklappt",
        nochmal: () => void schnittSichern(),
      });
    } finally {
      setSchnittSaving(false);
    }
  };

  const goBack = () => {
    if (dirty || stilGeaendert || schnittGeaendert) setLeaveOpen(true);
    else router.push(backHref);
  };

  /* Wo stehe ich in diesem Video, und wo geht es weiter? */
  const nr = geschwister.indexOf(clipId);
  const vorher = nr > 0 ? geschwister[nr - 1] : null;
  const nachher = nr >= 0 && nr < geschwister.length - 1 ? geschwister[nr + 1] : null;

  return (
    <>
      {/* Der Weg hierher. Er endet bei „Clips prüfen", und der Link dorthin führt in dieselbe
          Liste zurück: Filter und Scrollstand werden dort wiederhergestellt. */}
      <nav aria-label="Pfad" className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-text-2">
        <Link href="/" className="hover:text-text hover:underline">
          Meine Videos
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <Link href={`/projekte/${sourceId}`} className="max-w-[220px] truncate hover:text-text hover:underline">
          {sourceTitle}
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <Link href={`/projekte/${sourceId}/clips`} className="hover:text-text hover:underline">
          Clips prüfen
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <span className="text-text">Clip bearbeiten</span>
      </nav>

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
            {/* Die Laenge kommt aus dem aktuellen Schnitt und nicht aus dem gebauten Video: nach
              * einer Kuerzung stuende hier sonst weiter die alte Dauer. */}
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-text-2">
              <span>
                {ASPECT_LABELS[aspect]}, {formatClipDuration(neueDauer || durationS)}
              </span>
              {/* Der Speicherstand gehört in die Kopfzeile: er gilt für die ganze Seite, und
                  unten am Ende eines Bereichs sieht man ihn nur, wenn man dort gerade ist. */}
              <span aria-hidden="true" className="text-text-3">
                ·
              </span>
              <span className={offeneAenderungen ? "text-attention" : "text-text-3"} role="status" aria-live="polite">
                {offeneAenderungen ? "Nicht gespeichert" : "Gespeichert"}
              </span>
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Von Clip zu Clip, ohne über die Liste zu gehen. Wer vierzehn Clips durchsieht, will
              nicht vierzehnmal scrollen und suchen. */}
          {geschwister.length > 1 && (
            <div className="flex items-center gap-1 rounded-pill border border-line px-1 py-1">
              {vorher ? (
                <Link
                  href={`/projekte/${sourceId}/clips/${vorher}`}
                  aria-label="Voriger Clip"
                  className="transition-soft inline-flex h-7 items-center rounded-pill px-2.5 text-sm text-text-2 hover:bg-white/10 hover:text-text"
                >
                  Zurück
                </Link>
              ) : (
                <span className="inline-flex h-7 items-center px-2.5 text-sm text-text-3">Zurück</span>
              )}
              <span className="px-1.5 text-xs tabular-nums text-text-3">
                Clip {nr + 1} von {geschwister.length}
              </span>
              {nachher ? (
                <Link
                  href={`/projekte/${sourceId}/clips/${nachher}`}
                  aria-label="Nächster Clip"
                  className="transition-soft inline-flex h-7 items-center rounded-pill px-2.5 text-sm text-text-2 hover:bg-white/10 hover:text-text"
                >
                  Weiter
                </Link>
              ) : (
                <span className="inline-flex h-7 items-center px-2.5 text-sm text-text-3">Weiter</span>
              )}
            </div>
          )}
          <ButtonLink href={`/projekte/${sourceId}/transkript`} variant="ghost" size="sm">
            Transkript anzeigen
          </ButtonLink>
        </div>
      </div>

      {/* Der Arbeitsplatz: links das Video, rechts die Aufgabe.
        *
        * Die Vorschau bekommt eine eigene Spalte und bleibt beim Scrollen stehen. Sie schwebt
        * nicht über den Bedienelementen, sondern hat Platz, der ihr gehört - deshalb verdeckt sie
        * nichts. Vorher lag alles untereinander: beim Scrollen zu den Untertiteln war das Video
        * weg, und rechts blieb eine große leere Fläche.
        *
        * Die Breite: 380 Pixel für das Video, der Rest für die Arbeit. Auf einem breiten
        * Bildschirm wird damit die Arbeitsfläche breiter und nicht das Video größer - ein
        * Hochformat-Video, das die halbe Seite einnimmt, hilft niemandem. */}
      <div className="grid gap-5 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] lg:items-start">
        {/* Auf schmalen Bildschirmen gibt es keine zweite Spalte. Dann wird aus der Vorschau
            eine schmale Leiste, die oben kleben bleibt: kleiner, aber sichtbar. Sie steht im
            Fluss und verdeckt nichts - unter ihr geht die Seite weiter. */}
        <div className="sticky top-0 z-20 -mx-4 border-b border-line bg-[#0a0a13]/95 px-4 py-2 backdrop-blur max-lg:flex max-lg:flex-wrap max-lg:items-start max-lg:gap-3 lg:top-4 lg:mx-0 lg:self-start lg:border-0 lg:bg-transparent lg:px-0 lg:py-0 lg:backdrop-blur-none">
          {/* Welche der beiden Fassungen läuft gerade? Am veralteten gebauten Video steht es
              direkt am Umschalter: dort stellt sich die Frage, ob das noch stimmt. */}
          {clipSrc && (
            <div className="mb-3 flex gap-1 rounded-pill border border-line p-1 max-lg:order-2 max-lg:mb-0 max-lg:min-w-[200px] max-lg:flex-1">
              {[
                { an: false, name: "Mit deinen Änderungen", titel: "Zeigt, was jetzt eingestellt ist" },
                {
                  an: true,
                  name: gebautesVeraltet ? "Zuletzt geclippt · alt" : "Zuletzt geclippt",
                  titel: "Das Ergebnis des letzten Clippens",
                },
              ].map((w) => (
                <button
                  key={String(w.an)}
                  type="button"
                  title={w.titel}
                  onClick={() => setZeigeGebautes(w.an)}
                  aria-pressed={zeigeGebautes === w.an}
                  className={cn(
                    "transition-soft flex-1 rounded-pill px-3 py-1.5 text-xs",
                    zeigeGebautes === w.an ? "bg-white/10 text-text" : "text-text-2 hover:text-text",
                  )}
                >
                  {w.name}
                </button>
              ))}
            </div>
          )}

          <div className="max-lg:order-1 max-lg:w-[120px] max-lg:shrink-0">
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
            spielen={spielen}
            onLaeuft={setLaeuft}
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
              clipStart={vorschauStart}
              clipEnd={vorschauEnde}
              luecken={vorschauLuecken}
              zeit={currentTime}
              onTime={setCurrentTime}
              seekTo={seekTo}
              spielen={spielen}
              onLaeuft={setLaeuft}
              shots={shots}
              zeitmarken={markenSicht}
              stil={stil}
              woerter={clipWords}
              onCaptionHoehe={canEdit ? (px) => setStil((v) => ({ ...v, bottom_margin_px: px })) : undefined}
            />
          )}
          </div>

          {/* Der Stand des gebauten Videos, kurz. Die lange Fassung mit allen Sätzen steht unter
            * „Fertigstellen"; hier unter dem Video nahm sie ein Drittel der Höhe ein, die dem
            * Video gehört. */}
          {/* Unter „Fertigstellen" steht die ausführliche Fassung derselben Karte. Beide zugleich
              wäre dieselbe Aussage zweimal auf einem Bildschirm. */}
          <div hidden={bereich === "fertig"} className="mt-3 max-lg:order-3 max-lg:mt-0 max-lg:w-full">
            <VorschauStatus
              kompakt
              onMehr={() => setBereich("fertig")}
              sourceId={sourceId}
              clipId={clipId}
              canEdit={canEdit}
              offeneAenderungen={offeneAenderungen}
              offeneUntertitel={offeneUntertitel}
              onNeuGebaut={() => router.refresh()}
              status={clipStatus}
              hatDatei={Boolean(clipSrc)}
              plan={renderPlan}
              renderFehler={renderFehler}
              transkriptVersion={transkriptVersion}
              stil={stilGespeichert}
              schnitt={gesichert}
              zeitmarken={marken}
            />
          </div>

        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {/* Die vier Bereiche. Alle bleiben im Baum und werden nur ausgeblendet: ein Wechsel
              setzt deshalb nichts zurück, weder die Abspielposition noch eine begonnene
              Texteingabe noch den gewählten Abschnitt in der Timeline. */}
          <div role="tablist" aria-label="Arbeitsbereich" className="flex flex-wrap gap-1 rounded-inner border border-line p-1">
            {BEREICHE.map((b) => (
              <button
                key={b.id}
                type="button"
                role="tab"
                aria-selected={bereich === b.id}
                title={b.satz}
                onClick={() => setBereich(b.id)}
                className={cn(
                  "transition-soft flex-1 rounded-[10px] px-3 py-2 text-sm",
                  bereich === b.id ? "bg-white/10 font-medium text-text" : "text-text-2 hover:text-text",
                )}
              >
                {b.name}
                {b.id === "fertig" && offeneUntertitel > 0 && (
                  <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-attention align-middle" aria-hidden="true" />
                )}
              </button>
            ))}
          </div>

          <div hidden={bereich !== "schnitt"} className="flex min-w-0 flex-col gap-4">
          <Timeline
            bereichVonS={bereichVon}
            bereichBisS={bereichBis}
            schnitt={schnitt}
            onSchnitt={(neu) => schnittSetzen(neu)}
            onZiehen={schnittZiehen}
            onZiehenFertig={schnittLoslassen}
            quelleDauerS={quelleDauerS}
            zeit={currentTime}
            onSeek={seek}
            laeuft={laeuft}
            onPlayPause={() => setSpielen((n) => n + 1)}
            wellenform={wellenform}
            wellenformStand={wellenformStand}
            filmstreifen={streifenBilder}
            shots={shots}
            zeitmarken={markenSicht}
            onMarkeWeg={(abS) => markenAendern((vorher) => vorher.filter((x) => x.ab_s !== abS))}
            onMarkeVerschieben={(vonS, nachS) =>
              markenAendern((vorher) =>
                vorher
                  .map((x) => (Math.abs(x.ab_s - vonS) < 1e-6 ? { ...x, ab_s: Math.round(nachS * 100) / 100 } : x))
                  .sort((a, b) => a.ab_s - b.ab_s),
              )
            }
            markeBeschriftung={(m) => markeBeschreibung(m, auswahlAusShots)}
            canEdit={canEdit}
            kannZurueck={zurueckStapel.length > 0}
            kannVor={vorStapel.length > 0}
            onZurueck={zurueck}
            onVor={vor}
          />

          {canEdit && (
            <GlassCard padding="md" selected={schnittGeaendert}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-col gap-1">
                  <p className="text-sm text-text">
                    {schnittGeaendert
                      ? `Schnitt geändert, noch nicht gespeichert. Neue Länge ${neueDauer.toFixed(1).replace(".", ",")} s.`
                      : schnittVeraltet
                        ? "Schnitt gespeichert. Das geclippte Video hat ihn noch nicht."
                        : `Gespeichert. Länge ${neueDauer.toFixed(1).replace(".", ",")} s.`}
                  </p>
                  {(schnittGeaendert || schnittVeraltet) && (
                    <p className="text-sm text-text-2">{'Links unter „Mit deinen Änderungen“ siehst du ihn schon.'}</p>
                  )}
                </div>
                <Button
                  variant={schnittGeaendert ? "primary" : "ghost"}
                  disabled={!schnittGeaendert || schnittSaving}
                  onClick={() => void schnittSichern()}
                >
                  {schnittSaving ? "Wird gespeichert" : "Schnitt speichern"}
                </Button>
              </div>
            </GlassCard>
          )}

          {/* Der Bildausschnitt gehört zum Schneiden: beides hängt an der Stelle, an der der
              Abspielkopf steht. Vorher lag er in einer eigenen Spalte weit unten, und man musste
              zwischen Timeline und Ausschnitt hin und her scrollen. */}
          <Bildausschnitt
            zeit={currentTime}
            shots={shots}
            zeitmarken={markenSicht}
            onMarke={(m) =>
              markenAendern((vorher) =>
                [...vorher.filter((x) => Math.abs(x.ab_s - m.ab_s) > 0.35), m].sort((a, b) => a.ab_s - b.ab_s),
              )
            }
            onMarkeWeg={(abS) => markenAendern((vorher) => vorher.filter((x) => x.ab_s !== abS))}
            /* Beim Ziehen am Nähe-Regler: nur die Vorschau nachführen. Nicht speichern und keinen
               Schritt im Verlauf anlegen - sonst stünden nach einer Bewegung von 1,0 nach 1,6 ein
               Dutzend Speichervorgänge im Netz und ebenso viele Schritte in „Rückgängig". */
            onVorschau={(m) =>
              setMarkenVorschau(
                m == null
                  ? null
                  : [...markenRef.current.filter((x) => Math.abs(x.ab_s - m.ab_s) > 0.35), m].sort((a, b) => a.ab_s - b.ab_s),
              )
            }
            quelleBreite={quelleBreite}
            canEdit={canEdit}
          />
          </div>

          <div hidden={bereich !== "text"} className="flex min-w-0 flex-col gap-4">
            {hasText ? (
              <ClipTextEditor
                words={words}
                original={original}
                wordFrom={wordFrom}
                wordTo={wordTo}
                speakers={speakers}
                speakerNames={speakerNames}
                sprechertrennung={sprechertrennung}
                currentTime={currentTime}
                canEdit={canEdit}
                onEditWord={editWord}
                onChangeSpeaker={changeSpeaker}
                onSeek={seek}
                markeVorhanden={markeVorhanden}
              />
            ) : (
              <GlassCard padding="md">
                <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
              </GlassCard>
            )}

            {canEdit && hasText && (
              <GlassCard padding="md" selected={dirty}>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <p className="text-sm text-text-2">{dirty ? "Du hast etwas geändert." : "Nichts geändert."}</p>
                  <Button variant={dirty ? "primary" : "ghost"} disabled={!dirty || saving} onClick={save}>
                    {saving ? "Wird gespeichert" : "Text speichern"}
                  </Button>
                </div>
                {/* Immer im Baum, auch leer: ein Screenreader kündigt eine Live-Region nur an,
                    wenn sie schon dastand, bevor sich ihr Inhalt ändert (WCAG 2.2, 4.1.3). */}
                <div role="status" aria-live="polite" className={cn("flex flex-wrap items-center gap-3", message && "mt-3")}>
                  {message && (
                    <p className={cn("text-sm", message.tone === "ok" ? "text-text" : "text-attention")}>{message.text}</p>
                  )}
                  {message?.nochmal && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          const wieder = message.nochmal;
                          setMessage(null);
                          wieder?.();
                        }}
                      >
                        Nochmal versuchen
                      </Button>
                    )}
                  </div>
              </GlassCard>
            )}
          </div>

          <div hidden={bereich !== "untertitel"} className="flex min-w-0 flex-col gap-4">
            <CaptionStudio
              stil={stil}
              onChange={setStil}
              vorlagen={vorlagen}
              onVorlagenChange={setVorlagen}
              canEdit={canEdit}
              gespeichert={!stilGeaendert}
              speichern={() => void stilSpeichern()}
              zuruecksetzen={() => setStil({})}
              saving={stilSaving}
              schriftenVorhanden={schriftenVorhanden}
              markenFarben={markenFarben}
              woerter={clipWords}
              onSeek={seek}
            />
          </div>

          {/* Fertigstellen: was noch offen ist, das Bauen und der Download. Alles, was man ganz
              zum Schluss braucht, an einer Stelle statt über die Seite verteilt. */}
          <div hidden={bereich !== "fertig"} className="flex min-w-0 flex-col gap-4">
            <VorschauStatus
              sourceId={sourceId}
              clipId={clipId}
              canEdit={canEdit}
              offeneAenderungen={offeneAenderungen}
              offeneUntertitel={offeneUntertitel}
              onNeuGebaut={() => router.refresh()}
              status={clipStatus}
              hatDatei={Boolean(clipSrc)}
              plan={renderPlan}
              renderFehler={renderFehler}
              transkriptVersion={transkriptVersion}
              stil={stilGespeichert}
              schnitt={gesichert}
              zeitmarken={marken}
            />

            <GlassCard padding="md" className="flex flex-col gap-3">
              <p className="text-sm font-medium text-text">Was noch offen ist</p>
              {offeneAenderungen ? (
                <p className="text-sm text-attention">
                  {"Es gibt ungespeicherte Änderungen. Geclippt wird der gespeicherte Stand."}
                </p>
              ) : null}
              {offeneUntertitel > 0 ? (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm text-text-2">
                    {offeneUntertitel === 1
                      ? "Ein Untertitel ragt über den sicheren Bereich hinaus."
                      : `${offeneUntertitel} Untertitel ragen über den sicheren Bereich hinaus.`}
                  </p>
                  <Button size="sm" variant="ghost" onClick={() => setBereich("untertitel")}>
                    Zu den Untertiteln
                  </Button>
                </div>
              ) : null}
              {/* Die Fassung der Marke. Sie steht hier, weil hier auch der Knopf zum Neuclippen
                  sitzt: die Antwort auf „meine Marke hat sich geändert" ist genau dieser Knopf. */}
              {markenFassung && fassungSatz(markenFassung) && (
                <p className={cn("text-sm", markenFassung.stand === "aelter" ? "text-attention" : "text-text-3")}>
                  {markenName ? `Marke ${markenName}: ` : ""}
                  {fassungSatz(markenFassung)}
                </p>
              )}
              {/* Die Befunde zum Clip selbst. Sie standen bisher nur in der Clip-Übersicht - also
                  nicht auf der Seite, auf der man den Clip ansieht und freigibt. Ein Schnitt, der
                  eine Verneinung wegschneidet, gehört genau hierher. */}
              {befunde.map((b, i) => (
                <p key={i} className={cn("text-sm", b.schwere === "fehler" ? "text-attention" : "text-text-2")}>
                  {b.schwere === "fehler" ? "Fehler: " : "Hinweis: "}
                  {b.text}
                </p>
              ))}
              {!offeneAenderungen && offeneUntertitel === 0 && befunde.length === 0 && !(markenFassung && markenFassung.stand === "aelter") && (
                <p className="text-sm text-text-2">Nichts. Alles gespeichert, keine offenen Untertitel.</p>
              )}
              <ButtonLink href={`/projekte/${sourceId}/clips`} variant="ghost" size="sm" className="self-start">
                Zur Clip-Übersicht mit dem Download
              </ButtonLink>
            </GlassCard>
          </div>
        </div>
      </div>

      <Modal
        open={leaveOpen}
        onClose={() => setLeaveOpen(false)}
        title="Willst du die Seite wirklich verlassen?"
        description={`Nicht gespeichert: ${offeneListe}. Wenn du jetzt gehst, ist das weg.`}
      >
        {/* Drei Wege statt zwei. „Hier bleiben" und „ohne Speichern gehen" liessen den einzigen
            Ausgang aus, den man eigentlich will: speichern und dann gehen. Wer das nicht
            angeboten bekommt, bleibt, sucht den Speicherknopf und versucht es noch einmal. */}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setLeaveOpen(false)}>
            Hier bleiben
          </Button>
          <Button variant="danger" onClick={() => router.push(backHref)}>
            Ohne Speichern gehen
          </Button>
          <Button
            disabled={saving || stilSaving || schnittSaving}
            onClick={async () => {
              if (schnittGeaendert) await schnittSichern();
              if (stilGeaendert) await stilSpeichern();
              if (dirty) await save();
              router.push(backHref);
            }}
          >
            Speichern und gehen
          </Button>
        </div>
      </Modal>
    </>
  );
}
