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
import type { Aspect, ClipStatus, RenderShot, TranscriptVersion, TranscriptWord, Zeitmarke } from "@/lib/repo/types";
import { VorschauStatus } from "./VorschauStatus";
import { Bildausschnitt, beschreibung as markeBeschreibung } from "./Bildausschnitt";
import { Timeline, luecken } from "./timeline/Timeline";
import { useFilmstreifen } from "./useFilmstreifen";
import type { WellenformDaten, WellenformStand } from "./timeline/Wellenform";
import {
  dauer as schnittDauer,
  inClipzeit,
  gleich as schnittGleich,
  type Schnitt,
} from "@/lib/clips/schnitt";
import { pruefen } from "@/lib/clips/untertitel-pruefung";
import { dialogOffen, leertasteGehoertDemElement, tipptGerade } from "@/lib/tastatur";
import { rueckwegMerken } from "@/lib/clips/rueckweg";
import {
  dauerAendern as effektDauer,
  gleich as effekteGleich,
  entfernen as effektEntfernen,
  lesen as effekteLesen,
  verschieben as effektVerschieben,
  type Effekt,
} from "@/lib/clips/effekte";
import { EffektListe } from "./EffektListe";
import { MusikListe } from "./MusikListe";
import { gleich as musikGleich, lesen as musikLesen, type Musik } from "@/lib/clips/musik";
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
  /* Effekte auf der Clip-Zeitachse (Migration 0015). */
  effekte: Effekt[] | null;
  /* Musik unter dem Clip. Null heisst: keine. */
  musik: Musik | null;
  shots: RenderShot[];
  quelleBreite: number | null;
  /* Der gespeicherte Schnitt: welche Abschnitte der Quelle dieser Clip zeigt. */
  komposition: Schnitt;
  /* Der Schnitt, der im gebauten Video steckt. Weicht er vom gespeicherten ab, zeigt das Video
   * ein altes Ergebnis, und das muss dastehen. */
  quelleDauerS: number;
  wellenformSrc: string | null;
  /* Ist das Video fertig analysiert? Ohne das lässt sich nicht sagen, ob eine fehlende Tonspur
   * noch kommt oder nie kommen wird. */
  quelleFertig: boolean;
  /* Die Farben dieser Marke, als schnelle Wahl bei den Untertiteln. Eine Agentur soll die
   * Kundenfarbe nicht bei jedem Clip aus einem Farbrad suchen. */
  markenFarben: string[];
  clipStatus: ClipStatus;
  renderFehler: string | null;
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
 * Text, dann das Aussehen.
 *
 * Ein vierter Bereich „Fertigstellen" stand hier einmal: Renderstand, eine Liste „Was noch offen
 * ist" und ein Weg zurück in die Übersicht. Er ist weg. Seit Speichern sofort neu clippt, gibt es
 * nichts mehr fertigzustellen - der Stand des Videos steht ohnehin dauerhaft unter der Vorschau,
 * und der Weg zurück steht in der Brotkrume. */
export type Bereich = "schnitt" | "text" | "untertitel";

const BEREICHE: { id: Bereich; name: string; satz: string }[] = [
  { id: "schnitt", name: "Schnitt", satz: "Timeline und Bildausschnitt" },
  { id: "text", name: "Text", satz: "Gesprochene Wörter prüfen" },
  { id: "untertitel", name: "Untertitel", satz: "Aussehen, Position, Lesbarkeit" },
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
  effekte: effekteAnfang,
  musik: musikAnfang,
  shots,
  quelleBreite,
  komposition,
  quelleDauerS,
  wellenformSrc,
  quelleFertig,
  markenFarben,
  clipStatus,
  renderFehler,
  markeVorhanden,
  schriftenVorhanden,
}: Props) {
  const router = useRouter();
  const backHref = `/projekte/${sourceId}/clips`;
  /* Beim Zurückgehen eine Notiz hinterlassen: nur dann holt die Liste Filter und Scrollstand
   * wieder hervor. Wer frisch auf die Liste kommt, soll bei „Alle" anfangen. */
  const zurueckZurListe = useCallback(() => {
    rueckwegMerken(sourceId);
    router.push(backHref);
  }, [router, backHref, sourceId]);

  const [original, setOriginal] = useState<TranscriptWord[]>(initialWords);
  /* Der Wortlaut, wie er beim Öffnen der Seite dastand - und der bleibt so.
   *
   * ``original`` ist nach dem Speichern der gespeicherte Stand; daran hängt, ob etwas offen ist.
   * Für ein aus dem Untertitel genommenes Wort ist das aber genau das Falsche: dort steht danach
   * ein leerer Text, und damit wäre weder anzuzeigen, welches Wort durchgestrichen dasteht, noch
   * es zurückzuholen. Diese Liste wird nie überschrieben.
   *
   * Grenze, die bleibt: ein Wort, das in einer FRÜHEREN Sitzung genommen und gespeichert wurde,
   * ist auch hier schon leer. Sein Wortlaut steht nur in der Korrekturliste auf dem Server und
   * wird nicht mitgeladen. */
  const [gesprochen] = useState<TranscriptWord[]>(initialWords);
  const [words, setWords] = useState<TranscriptWord[]>(initialWords);
  const [corrections, setCorrections] = useState<Map<number, Correction>>(new Map());
  const [currentTime, setCurrentTime] = useState(clipStart);
  const [seekTo, setSeekTo] = useState<{ at: number; nonce: number } | null>(null);
  const [saving, setSaving] = useState(false);
  /* Bei einem Fehler steht in ``nochmal``, was zu wiederholen ist. Eine Meldung ohne Weg zurueck
   * laesst den Nutzer mit seiner Arbeit im Browser sitzen und sonst nichts. */
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; nochmal?: () => void } | null>(null);
  /* Wohin es gehen soll, sobald über die ungespeicherten Änderungen entschieden ist.
   *
   * Vorher war das ein blosses true/false und galt nur für den Weg zurück zur Liste. „Zurück",
   * „Weiter" und der Wechsel zwischen Schnitt, Text und Untertiteln gingen daran vorbei - die
   * Änderungen waren weg, ohne dass jemand gefragt wurde. Jetzt merkt sich die Seite den Weg und
   * geht ihn erst nach der Antwort. */
  const [verlassen, setVerlassen] = useState<{ was: string; gehen: () => void } | null>(null);

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
  const abspielen = useCallback(() => setSpielen((n) => n + 1), []);

  /* Leertaste spielt ab und hält an - im ganzen Fenster, nicht nur auf der Timeline.
   *
   * Bisher lag das Kürzel am Timeline-Element: es wirkte erst, wenn man die Timeline vorher
   * angeklickt hatte. Wer den Text prüft oder an den Untertiteln stellt, drückt die Leertaste und
   * es passiert nichts, obwohl direkt daneben ein Video steht. Beim Transkript ist es längst so,
   * und dort erwartet es jeder auch hier.
   *
   * Drei Fälle bleiben ausgenommen: ein Textfeld (dort ist die Leertaste ein Leerzeichen), ein
   * Knopf oder Reiter unter dem Fokus (dort löst sie ihn aus) und ein offener Dialog. */
  useEffect(() => {
    const beiTaste = (e: KeyboardEvent) => {
      if (e.code !== "Space" && e.key !== " ") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (tipptGerade(e.target) || leertasteGehoertDemElement(e.target) || dialogOffen()) return;
      e.preventDefault();
      abspielen();
    };
    document.addEventListener("keydown", beiTaste);
    return () => document.removeEventListener("keydown", beiTaste);
  }, [abspielen]);

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
  const neueDauer = schnittDauer(schnitt);

  /* Die Effekte dieses Clips.
   *
   * Sie kommen entweder vom Menschen oder von der Automatik des letzten Renderlaufs - in beiden
   * Fällen stehen sie am Clip und lassen sich hier verschieben, verlängern und entfernen. Eine
   * leere Liste wird ausdrücklich gespeichert: sie heisst „ich will keine", und der nächste
   * Renderlauf legt dann auch keine automatischen mehr an. */
  const [effekte, setEffekte] = useState<Effekt[]>(() => effekteLesen(effekteAnfang ?? [], schnittDauer(komposition)));
  const [effekteGesichert, setEffekteGesichert] = useState<Effekt[]>(effekte);
  const effekteGeaendert = !effekteGleich(effekte, effekteGesichert);
  /* Ein Knopf für beides: Schnitt und Effekte hängen an derselben Zeitleiste, und zwei
   * Speicherknöpfe nebeneinander sind eine Auswahlaufgabe. */
  /* Die Länge des Clips in Clipzeit: daran hängt, wie weit ein Effekt geschoben werden darf. */
  const clipDauer = useMemo(() => schnittDauer(schnitt), [schnitt]);

  /* Die Musik dieses Clips, und wie lang das Stück ist.
   *
   * Die Länge kommt nicht vom Server: sie steht in der Datei, und die kennt der Browser, sobald
   * er sie geladen hat. Ohne sie lässt sich nicht sagen, wie weit sich die Spur schieben darf -
   * deshalb bleibt sie bis dahin fest statt zu raten. */
  const [musik, setMusik] = useState<Musik | null>(() => musikLesen(musikAnfang));
  const [musikGesichert, setMusikGesichert] = useState<Musik | null>(musik);
  const [musikDauer, setMusikDauer] = useState<number | null>(null);
  const [musikLaeuft, setMusikLaeuft] = useState(false);
  const [musikFehler, setMusikFehler] = useState<string | null>(null);
  const musikGeaendert = !musikGleich(musik, musikGesichert);
  /* Ein Knopf für alles: Schnitt, Effekte und Musik hängen an derselben Zeitleiste, und drei
   * Speicherknöpfe nebeneinander sind eine Auswahlaufgabe. */
  const etwasGeaendert = schnittGeaendert || effekteGeaendert || musikGeaendert;

  /* Woher die Musikdatei kommt. Der Ablageschlüssel hängt als Kennung dran: lädt jemand ein
   * anderes Stück hoch, ändert sich die Adresse, und der Browser holt die neue Datei statt der
   * alten aus seinem Zwischenspeicher. */
  const musikDatei = musik?.datei ?? null;
  const musikSrc = useMemo(
    () =>
      musikDatei
        ? `/api/projects/${sourceId}/clips/${clipId}/musik/datei?v=${encodeURIComponent(musikDatei)}`
        : null,
    [musikDatei, sourceId, clipId],
  );

  /* Die Länge des Stücks messen, sobald eine Datei da ist. Ein Audio-Element im Speicher, kein
   * Abspielen: das geht in jedem Browser und kostet nichts.
   *
   * Ohne diese Zahl hätte das Verschieben der Musikspur keine Grenze - man könnte über das Ende
   * des Stücks hinausziehen und bekäme Stille. */
  useEffect(() => {
    if (!musikSrc) {
      setMusikDauer(null);
      return undefined;
    }
    const url = musikSrc;
    const a = new Audio();
    let weg = false;
    const fertig = () => {
      if (!weg && Number.isFinite(a.duration)) setMusikDauer(a.duration);
    };
    a.addEventListener("loadedmetadata", fertig);
    a.preload = "metadata";
    a.src = url;
    return () => {
      weg = true;
      a.removeEventListener("loadedmetadata", fertig);
      a.src = "";
    };
  }, [musikSrc]);

  /* Musik hochladen. Sie wird SOFORT gespeichert und nicht erst mit dem Speichern-Knopf: eine
   * Datei liegt danach ohnehin auf dem Server, und ein „ungespeichertes Hochladen" gibt es nicht. */
  const musikHochladen = useCallback(
    async (datei: File) => {
      setMusikLaeuft(true);
      setMusikFehler(null);
      try {
        const form = new FormData();
        form.append("datei", datei);
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/musik`, { method: "POST", body: form });
        const d = (await res.json()) as { musik?: unknown; error?: string };
        if (!res.ok) throw new Error(d.error ?? "Das Hochladen hat nicht geklappt");
        const neu = musikLesen(d.musik);
        setMusik(neu);
        setMusikGesichert(neu);
      } catch (err) {
        setMusikFehler(err instanceof Error ? err.message : "Das Hochladen hat nicht geklappt");
      } finally {
        setMusikLaeuft(false);
      }
    },
    [sourceId, clipId],
  );

  /* Eine Änderung an den Effekten wird NICHT sofort gespeichert.
   *
   * Vorher ging jede Bewegung sofort an den Server. Das war unsichtbar: unten stand „Schnitt
   * gespeichert", und wer einen Effekt setzte, sah keinen Hinweis, dass sich etwas geändert hat -
   * und hielt es für verloren. Jetzt gehören Schnitt und Effekte demselben Knopf. */
  const effekteAendern = useCallback((naechste: Effekt[]) => setEffekte(naechste), []);

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
  const offeneAenderungen = dirty || stilGeaendert || schnittGeaendert || effekteGeaendert || musikGeaendert;
  /* Was genau offen ist. „Du hast etwas geändert" lässt den Nutzer raten, was er verliert. */
  const offeneListe = [
    schnittGeaendert ? "der Schnitt" : null,
    effekteGeaendert ? "die Effekte" : null,
    musikGeaendert ? "die Musik" : null,
    dirty ? "der Text" : null,
    stilGeaendert ? "die Untertitel" : null,
  ]
    .filter(Boolean)
    .join(", ") || "nichts";

  /* Wörter aus dem Untertitel nehmen.
   *
   * Nicht dasselbe wie eine Korrektur: ``editWord`` weist leeren Text ausdrücklich ab, weil ein
   * leeres Korrekturfeld ein Versehen ist. Hier ist die Leere die Absicht. Das Wort behält seine
   * Zeiten - das folgende bleibt dadurch an seiner Stelle - und fällt im Renderer aus den Karten
   * heraus (captions_de.sichtbare_woerter).
   *
   * Gesagt bleibt gesagt: am Ton ändert sich nichts. Wer ein Wort wirklich aus dem Video haben
   * will, schneidet es unter „Schnitt" heraus. */
  const deleteWords = useCallback(
    (indices: number[]) => {
      setWords((prev) => {
        const next = [...prev];
        for (const i of indices) if (next[i] && next[i].text !== "") next[i] = { ...next[i], text: "" };
        return next;
      });
      setCorrections((prev) => {
        const next = new Map(prev);
        for (const i of indices) {
          const before = original[i];
          if (!before) continue;
          if (before.text === "") next.delete(i);
          else next.set(i, { old_text: before.text, new_text: "", add_to_vocab: false });
        }
        return next;
      });
    },
    [original],
  );

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
      /* Und gleich neu clippen, genau wie beim Schnitt. Ein geänderter Untertiteltext, der erst
       * beim nächsten Lauf im Bild landet, ist eine Aufgabe, die das Programm dem Menschen gibt,
       * obwohl es sie selbst erledigen kann. Schlägt das Anstossen fehl, ist das Speichern
       * trotzdem sicher - die Änderung liegt in der Datenbank. */
      try {
        const lauf = await fetch(`/api/projects/${sourceId}/clips/${clipId}/render`, { method: "POST" });
        /* 409 heisst: es läuft schon. Das ist kein Fehler, sondern genau das, was man wollte. */
        if (!lauf.ok && lauf.status !== 409) {
          const d = (await lauf.json()) as { error?: string };
          throw new Error(d.error ?? "Das Clippen liess sich nicht anstossen");
        }
        setMessage({ tone: "ok", text: "Gespeichert. Das Video wird geclippt." });
      } catch (err) {
        setMessage({
          tone: "error",
          text: `Gespeichert. Das Clippen liess sich nicht anstossen: ${
            err instanceof Error ? err.message : "unbekannter Fehler"
          }`,
        });
      }
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

  /* Ein Speichern für beides: Schnitt und Effekte.
   *
   * Der Schnitt zuerst, denn die Effekte werden am Server gegen die Cliplänge geprüft - und die
   * hängt am Schnitt. Andersherum würde ein Effekt an einer Stelle abgewiesen, die es nach dem
   * Speichern des Schnitts längst gibt. */
  const schnittSichern = async () => {
    setSchnittSaving(true);
    setMessage(null);
    try {
      if (schnittGeaendert) {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/schnitt`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ composition: schnitt }),
        });
        const data = (await res.json()) as { error?: string; composition?: Schnitt; needs_render?: boolean };
        if (!res.ok || !data.composition) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
        setSchnitt(data.composition);
        setGesichert(data.composition);
      }
      if (effekteGeaendert) {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/effekte`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ effekte }),
        });
        const data = (await res.json()) as { error?: string; effekte?: Effekt[]; needs_render?: boolean };
        if (!res.ok || !data.effekte) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
        setEffekte(data.effekte);
        setEffekteGesichert(data.effekte);
      }
      if (musikGeaendert) {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/musik`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ musik }),
        });
        const data = (await res.json()) as { error?: string; musik?: unknown };
        if (!res.ok) throw new Error(data.error ?? "Das Speichern hat nicht geklappt");
        setMusikGesichert(musikLesen(data.musik));
      }
      /* Und gleich neu clippen.
       *
       * „Gespeichert, das Video muss neu geclippt werden" war eine Aufgabe, die das Programm
       * dem Menschen gab, obwohl es sie selbst erledigen kann: es gibt nichts zu entscheiden.
       * Wer speichert, will das Ergebnis sehen. Der Lauf läuft im Hintergrund, die Vorschau
       * zeigt ihn an.
       *
       * Immer, nicht nur wenn schon einmal geclippt wurde: auch beim ersten Mal will man das
       * Ergebnis sehen, ohne noch einen Knopf zu suchen.
       *
       * Schlägt das Anstossen fehl, ist das kein verlorenes Speichern: die Änderung liegt sicher
       * in der Datenbank, und der Knopf „Video clippen" steht weiterhin daneben. */
      try {
        const res = await fetch(`/api/projects/${sourceId}/clips/${clipId}/render`, { method: "POST" });
        const data = (await res.json()) as { error?: string };
        /* 409 heisst: es läuft schon. Das ist kein Fehler, sondern genau das, was man wollte. */
        if (!res.ok && res.status !== 409) throw new Error(data.error ?? "Das Clippen liess sich nicht anstossen");
        setMessage({ tone: "ok", text: "Gespeichert. Das Video wird geclippt." });
      } catch (err) {
        setMessage({
          tone: "error",
          text: `Gespeichert. Das Clippen liess sich nicht anstossen: ${
            err instanceof Error ? err.message : "unbekannter Fehler"
          }`,
        });
      }
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

  /* Jeder Weg aus dieser Seite heraus geht hier durch. Ohne offene Änderungen sofort, sonst
   * erst die Frage. */
  const wechseln = (was: string, gehen: () => void) => {
    if (offeneAenderungen) setVerlassen({ was, gehen });
    else gehen();
  };
  const goBack = () => wechseln("zur Clip-Liste", zurueckZurListe);

  /* Alles speichern, was offen ist - in der Reihenfolge, in der es gehört: erst Schnitt und
   * Effekte (die stossen das Neuclippen an), dann Text und Untertitel. */
  const allesSpeichern = async () => {
    if (schnittGeaendert || effekteGeaendert) await schnittSichern();
    if (stilGeaendert) await stilSpeichern();
    if (dirty) await save();
  };

  /* Wo stehe ich in diesem Video, und wo geht es weiter? */
  const nr = geschwister.indexOf(clipId);
  const vorher = nr > 0 ? geschwister[nr - 1] : null;
  const nachher = nr >= 0 && nr < geschwister.length - 1 ? geschwister[nr + 1] : null;

  return (
    <>
      {/* Der Weg hierher. Zwei Stufen statt drei: der Videoname IST die Clip-Liste, seit die
          eigene Projektseite weggefallen ist. Der Link dorthin führt in dieselbe Liste zurück -
          Filter und Scrollstand werden dort wiederhergestellt. */}
      <nav aria-label="Pfad" className="mb-4 flex flex-wrap items-center gap-1.5 text-sm text-text-2">
        <Link href="/" className="hover:text-text hover:underline">
          Meine Videos
        </Link>
        <span aria-hidden="true" className="text-text-3">
          ›
        </span>
        <Link href={`/projekte/${sourceId}/clips`} className="max-w-[260px] truncate hover:text-text hover:underline">
          {sourceTitle}
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
                /* Ein Knopf und kein Link: ein Link geht sofort, und die Frage nach den
                   ungespeicherten Änderungen käme zu spät. */
                <button
                  type="button"
                  onClick={() => wechseln("zum vorigen Clip", () => router.push(`/projekte/${sourceId}/clips/${vorher}`))}
                  aria-label="Voriger Clip"
                  className="transition-soft inline-flex h-7 items-center rounded-pill px-2.5 text-sm text-text-2 hover:bg-white/10 hover:text-text"
                >
                  Zurück
                </button>
              ) : (
                <span className="inline-flex h-7 items-center px-2.5 text-sm text-text-3">Zurück</span>
              )}
              <span className="px-1.5 text-xs tabular-nums text-text-3">
                Clip {nr + 1} von {geschwister.length}
              </span>
              {nachher ? (
                <button
                  type="button"
                  onClick={() => wechseln("zum nächsten Clip", () => router.push(`/projekte/${sourceId}/clips/${nachher}`))}
                  aria-label="Nächster Clip"
                  className="transition-soft inline-flex h-7 items-center rounded-pill px-2.5 text-sm text-text-2 hover:bg-white/10 hover:text-text"
                >
                  Weiter
                </button>
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
          {/* Welche der beiden Fassungen läuft gerade: die Vorschau dessen, was eingestellt ist,
              oder das zuletzt geclippte Video. */}
          {clipSrc && (
            <div className="mb-3 flex gap-1 rounded-pill border border-line p-1 max-lg:order-2 max-lg:mb-0 max-lg:min-w-[200px] max-lg:flex-1">
              {[
                { an: false, name: "Mit deinen Änderungen", titel: "Zeigt, was jetzt eingestellt ist" },
                { an: true, name: "Zuletzt geclippt", titel: "Das Ergebnis des letzten Clippens" },
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
              effekte={effekte}
              clipStartQuelle={schnitt[0]?.start ?? 0}
              stil={stil}
              woerter={clipWords}
              musik={musik}
              musikSrc={musikSrc}
              schnitt={schnitt}
              onCaptionHoehe={canEdit ? (px) => setStil((v) => ({ ...v, bottom_margin_px: px })) : undefined}
            />
          )}
          </div>

          {/* Der Stand des geclippten Videos, kurz und immer sichtbar. Die ausführliche Fassung
              stand unter „Fertigstellen"; den Bereich gibt es nicht mehr, und gebraucht wurde sie
              auch nicht - hier steht dasselbe in einer Zeile. */}
          <div className="mt-3 max-lg:order-3 max-lg:mt-0 max-lg:w-full">
            <VorschauStatus
              kompakt
              sourceId={sourceId}
              clipId={clipId}
              canEdit={canEdit}
              offeneUntertitel={offeneUntertitel}
              onNeuGebaut={() => router.refresh()}
              status={clipStatus}
              hatDatei={Boolean(clipSrc)}
              renderFehler={renderFehler}
            />
          </div>

        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {/* Die drei Bereiche. Alle bleiben im Baum und werden nur ausgeblendet: ein Wechsel
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
                /* Schnitt, Text und Untertitel werden getrennt gespeichert. Wer mit offenen
                   Änderungen den Bereich wechselt, verlöre sie - also erst die Frage. */
                onClick={() => wechseln(`zu „${b.name}“`, () => setBereich(b.id))}
                className={cn(
                  "transition-soft flex-1 rounded-[10px] px-3 py-2 text-sm",
                  bereich === b.id ? "bg-white/10 font-medium text-text" : "text-text-2 hover:text-text",
                )}
              >
                {b.name}
                {b.id === "untertitel" && offeneUntertitel > 0 && (
                  <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-attention align-middle" aria-hidden="true" />
                )}
              </button>
            ))}
          </div>

          <div hidden={bereich !== "schnitt"} className="flex min-w-0 flex-col gap-4">
          <Timeline
            effekte={effekte}
            clipDauerS={clipDauer}
            onEffektVerschieben={(i, abS) => effekteAendern(effektVerschieben(effekte, i, abS, clipDauer))}
            onEffektDauer={(i, d) => effekteAendern(effektDauer(effekte, i, d, clipDauer))}
            onEffektWeg={(i) => effekteAendern(effektEntfernen(effekte, i))}
            musik={musik}
            musikDauerS={musikDauer}
            onMusikVerschieben={(abS) => setMusik((m) => (m ? { ...m, ab_s: abS } : m))}
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
            onPlayPause={abspielen}
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

          {/* Effekte. Unter dem Bildausschnitt, weil beides dasselbe beantwortet: wie das Bild
              sich bewegt. Die Liste ist bewusst eine Liste - es werden mehr Effekte dazukommen,
              und dann steht hier jeder für sich mit seiner eigenen Auswahl. */}
          <MusikListe
            musik={musik}
            canEdit={canEdit}
            laeuft={musikLaeuft}
            fehler={musikFehler}
            onAendern={setMusik}
            onHochladen={(d) => void musikHochladen(d)}
          />

          <EffektListe
            effekte={effekte}
            zeitImClip={inClipzeit(schnitt, currentTime)}
            clipDauer={clipDauer}
            canEdit={canEdit}
            onAendern={effekteAendern}
          />

          {/* Speichern ganz unten rechts, wo man nach dem Arbeiten hinkommt.
              Vorher stand hier eine ganze Karte mit einem Satz über den Speicherstand. Der Satz
              beantwortete eine Frage, die links unter der Vorschau schon beantwortet ist, und
              nahm dafür eine Zeile quer über die Seite. */}
          {canEdit && (
            <div className="flex justify-end">
              {/* Ein Knopf, ein Wort. Er ist aus, solange es nichts zu speichern gibt - ein
                  Knopf, der immer klickbar ist, sagt nichts darüber, ob etwas offen ist. */}
              <Button
                variant={etwasGeaendert ? "primary" : "ghost"}
                disabled={!etwasGeaendert || schnittSaving}
                onClick={() => void schnittSichern()}
              >
                {schnittSaving ? "Wird gespeichert" : "Speichern"}
              </Button>
            </div>
          )}
          </div>

          <div hidden={bereich !== "text"} className="flex min-w-0 flex-col gap-4">
            {hasText ? (
              <ClipTextEditor
                words={words}
                original={original}
                gesprochen={gesprochen}
                wordFrom={wordFrom}
                wordTo={wordTo}
                speakers={speakers}
                speakerNames={speakerNames}
                sprechertrennung={sprechertrennung}
                currentTime={currentTime}
                canEdit={canEdit}
                onEditWord={editWord}
                onDeleteWords={deleteWords}
                onChangeSpeaker={changeSpeaker}
                onSeek={seek}
                markeVorhanden={markeVorhanden}
              />
            ) : (
              <GlassCard padding="md">
                <p className="text-sm text-text-2">Zu diesem Clip steht kein Text bereit.</p>
              </GlassCard>
            )}

            {/* Nur der Knopf, unten rechts. Hier stand eine eigene Karte mit „Du hast etwas
                geändert." und darunter „Gespeichert. Wirkt, sobald das Video neu geclippt wird." -
                drei Zeilen für eine Handlung, und die letzte stimmte nicht mehr: Speichern clippt
                jetzt sofort neu. Dass etwas offen ist, steht oben in der Kopfzeile, und der Knopf
                ist grau, solange es nichts zu speichern gibt. */}
            {canEdit && hasText && (
              <div className="flex flex-wrap items-center justify-end gap-3">
                {/* Immer im Baum, auch leer: ein Screenreader kündigt eine Live-Region nur an,
                    wenn sie schon dastand, bevor sich ihr Inhalt ändert (WCAG 2.2, 4.1.3). */}
                <div role="status" aria-live="polite" className="mr-auto flex min-w-0 flex-wrap items-center gap-3">
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
                <Button variant={dirty ? "primary" : "ghost"} disabled={!dirty || saving} onClick={save}>
                  {saving ? "Wird gespeichert" : "Speichern"}
                </Button>
              </div>
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
        </div>
      </div>

      {/* Eine Frage für jeden Weg hinaus: zurück zur Liste, zum nächsten Clip, in einen anderen
          Bereich. Drei Antworten statt zwei - „hier bleiben" und „ohne Speichern gehen" liessen
          den einzigen Ausgang aus, den man eigentlich will: speichern und dann gehen. Wer das
          nicht angeboten bekommt, bleibt, sucht den Speicherknopf und versucht es noch einmal. */}
      <Modal
        open={verlassen != null}
        onClose={() => setVerlassen(null)}
        title="Du hast etwas geändert"
        description={`Nicht gespeichert: ${offeneListe}. Was soll damit passieren, bevor es ${verlassen?.was ?? "weitergeht"} geht?`}
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setVerlassen(null)}>
            Hier bleiben
          </Button>
          <Button
            variant="danger"
            onClick={() => {
              const weg = verlassen;
              setVerlassen(null);
              weg?.gehen();
            }}
          >
            Ohne Speichern
          </Button>
          <Button
            disabled={saving || stilSaving || schnittSaving}
            onClick={async () => {
              const weg = verlassen;
              await allesSpeichern();
              setVerlassen(null);
              weg?.gehen();
            }}
          >
            Speichern
          </Button>
        </div>
      </Modal>
    </>
  );
}
