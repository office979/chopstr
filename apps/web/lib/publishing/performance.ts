import type { MetricSnapshot, WindowFeedback } from "@/lib/repo/types-api";
import { SNAPSHOT_ERROR_CODES, type SnapshotErrorCode } from "./snapshot";

/* Lese-API für Performance (GET /api/v1/publications/{id}/metrics und /clips/{id}/performance). Rein:
 * Messreihe und Fenster kommen aus dem Repository, hier werden sie geordnet und um abgeleitete Werte ergänzt. */

export interface SnapshotOut {
  fetched_at: string;
  age_s: number | null;
  source: MetricSnapshot["source"];
  views: number | null;
  engaged_views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  follows: number | null;
  reach: number | null;
  avg_watch_time_s: number | null;
  skip_rate: number | null;
  engagement_rate: number | null;
  /* Nie der interne Fehlertext: nur Code und eine feste deutsche Meldung (publicSnapshotError) */
  error: SnapshotError | null;
}

export interface SnapshotError {
  code: SnapshotErrorCode | "fehler";
  message: string;
}

const SNAPSHOT_ERROR_MESSAGES: Record<SnapshotError["code"], string> = {
  nicht_konfiguriert: "Zahlen für diese Plattform sind noch nicht eingerichtet.",
  nicht_verbunden: "Diese Plattform gibt Zahlen nur über ein verbundenes Konto heraus.",
  keine_verbindung: "Die Verbindung zur Plattform fehlt oder ist abgelaufen.",
  nicht_gefunden: "Der Beitrag wurde nicht gefunden oder ist nicht öffentlich.",
  plattform_fehler: "Die Plattform hat nicht richtig geantwortet.",
  abgeschaltet: "Die Messung ist abgeschaltet.",
  ungueltig: "Die Publikation hat keine gültige Beitrags-ID.",
  messdienst_nicht_erreichbar: "Der Messdienst war nicht erreichbar.",
  messdienst_fehler: "Der Messdienst hat nicht richtig geantwortet.",
  konfiguration: "Der Messdienst ist nicht vollständig eingerichtet.",
  fehler: "Die Messung ist fehlgeschlagen.",
};

/* metric_snapshots.error ist "<code>: <interner Text>" (Worker, run_snapshot). Ältere Zeilen ohne Code
 * und unbekannte Codes werden zu "fehler". */
export function publicSnapshotError(raw: string | null): SnapshotError | null {
  if (!raw) return null;
  const head = /^([a-z_]+):/.exec(raw)?.[1];
  const code = head && (SNAPSHOT_ERROR_CODES as readonly string[]).includes(head) ? (head as SnapshotErrorCode) : "fehler";
  return { code, message: SNAPSHOT_ERROR_MESSAGES[code] };
}

/* (likes + comments + shares + saves) / views; fehlende Anteile zählen als 0, ohne Aufrufe kein Wert */
export function engagementRate(m: { views: number | null; likes: number | null; comments: number | null; shares: number | null; saves: number | null }): number | null {
  if (m.views == null || m.views <= 0) return null;
  const parts = [m.likes, m.comments, m.shares, m.saves];
  if (parts.every((p) => p == null)) return null;
  const sum = parts.reduce<number>((a, b) => a + (b ?? 0), 0);
  return Math.round((sum / m.views) * 1e6) / 1e6;
}

export function serializeSnapshot(s: MetricSnapshot): SnapshotOut {
  return {
    fetched_at: s.fetched_at,
    age_s: s.age_s,
    source: s.source,
    views: s.views,
    engaged_views: s.engaged_views,
    likes: s.likes,
    comments: s.comments,
    shares: s.shares,
    saves: s.saves,
    follows: s.follows,
    reach: s.reach,
    avg_watch_time_s: s.avg_watch_time_s,
    skip_rate: s.skip_rate,
    engagement_rate: engagementRate(s),
    error: publicSnapshotError(s.error),
  };
}

/* Plausibilitätsprüfung nach dem Vorbild der Aufrufkurven-Prüfung bei Content Rewards: springen die Aufrufe
 * zwischen zwei Messungen auf mehr als das Fünffache, während die Interaktionsrate unter 0,2 % bleibt, ist das
 * auffällig (gekaufte oder Bot-Aufrufe sehen so aus). Nur ein Hinweis, keine Sperre. Regelname: "sprung_ohne_interaktion". */
export const ANOMALY_GROWTH_FACTOR = 5;
export const ANOMALY_MAX_ENGAGEMENT = 0.002;

export interface Anomaly {
  auffaellig: boolean;
  regel: "sprung_ohne_interaktion" | null;
  zwischen: { von: string; bis: string } | null;
}

export function detectAnomaly(series: SnapshotOut[]): Anomaly {
  const ok = series.filter((s) => s.views != null && !s.error).sort((a, b) => a.fetched_at.localeCompare(b.fetched_at));
  for (let i = 1; i < ok.length; i++) {
    const prev = ok[i - 1].views as number;
    const cur = ok[i].views as number;
    if (prev > 0 && cur > prev * ANOMALY_GROWTH_FACTOR) {
      const rate = ok[i].engagement_rate;
      if (rate != null && rate < ANOMALY_MAX_ENGAGEMENT) {
        return { auffaellig: true, regel: "sprung_ohne_interaktion", zwischen: { von: ok[i - 1].fetched_at, bis: ok[i].fetched_at } };
      }
    }
  }
  return { auffaellig: false, regel: null, zwischen: null };
}

/* Letzte Messung mit Zahlen; fehlgeschlagene Abrufe zählen nicht als „neuester Stand“ */
export function latestSnapshot(snapshots: MetricSnapshot[]): SnapshotOut | null {
  const withNumbers = snapshots.filter((s) => !s.error && (s.views != null || s.likes != null || s.comments != null));
  if (!withNumbers.length) return null;
  const last = withNumbers.reduce((a, b) => (a.fetched_at >= b.fetched_at ? a : b));
  return serializeSnapshot(last);
}

export function serializeWindow(f: WindowFeedback) {
  return {
    window: f.metric_window,
    views: f.views,
    likes: f.likes,
    comments: f.comments,
    shares: f.shares,
    saves: f.saves,
    follows: f.follows,
    follows_per_1k: f.follows_per_1k,
    saves_per_1k: f.saves_per_1k,
    outlier_score: f.outlier_score,
    reward: f.reward,
    engagement_rate: engagementRate(f),
    fetched_at: f.fetched_at,
  };
}

const WINDOW_ORDER = ["6h", "48h", "7d", "manual"];

export interface SeriesQuery {
  since: string | null;
  limit: number;
}

export const SERIES_DEFAULT_LIMIT = 200;
export const SERIES_MAX_LIMIT = 1000;

/* ?since= (ISO) und ?limit= (1 bis 1000, Standard 200) lesen; Fehler als deutscher Text */
export function parseSeriesQuery(params: URLSearchParams): SeriesQuery | { error: string } {
  const sinceRaw = params.get("since");
  let since: string | null = null;
  if (sinceRaw) {
    const t = Date.parse(sinceRaw);
    if (!Number.isFinite(t)) return { error: "since muss ein Zeitpunkt nach ISO 8601 sein." };
    since = new Date(t).toISOString();
  }
  const limitRaw = params.get("limit");
  let limit = SERIES_DEFAULT_LIMIT;
  if (limitRaw != null && limitRaw !== "") {
    const n = Number(limitRaw);
    if (!Number.isInteger(n) || n < 1 || n > SERIES_MAX_LIMIT) return { error: `limit muss eine ganze Zahl zwischen 1 und ${SERIES_MAX_LIMIT} sein.` };
    limit = n;
  }
  return { since, limit };
}

/* Je Publikation die neuesten Zahlen: letzte Messung, sonst das jüngste feste Fenster. Summe über alle
 * Publikationen nur für Felder, die mindestens eine Publikation hat. */
export function buildClipPerformance<P extends { id: string }>(publications: P[], snapshots: MetricSnapshot[], feedback: WindowFeedback[]) {
  const rows = publications.map((p) => {
    const own = snapshots.filter((s) => s.publication_id === p.id);
    const windows = feedback
      .filter((f) => f.publication_id === p.id)
      .sort((a, b) => WINDOW_ORDER.indexOf(a.metric_window) - WINDOW_ORDER.indexOf(b.metric_window))
      .map(serializeWindow);
    const latest = latestSnapshot(own);
    const lastWindow = windows.filter((w) => w.window !== "manual").at(-1) ?? windows.at(-1) ?? null;
    return {
      publication: p,
      latest,
      windows,
      reward: lastWindow?.reward ?? null,
      ...detectAnomaly(own.map(serializeSnapshot)),
    };
  });
  const views = rows.map((r) => r.latest?.views ?? r.windows.at(-1)?.views ?? null);
  return {
    publications: rows,
    totals: { publications: rows.length, views: views.some((v) => v != null) ? views.reduce<number>((a, v) => a + (v ?? 0), 0) : null },
  };
}

export function buildPublicationMetrics(publicationId: string, snapshots: MetricSnapshot[], feedback: WindowFeedback[], query: SeriesQuery = { since: null, limit: SERIES_DEFAULT_LIMIT }) {
  const sorted = [...snapshots].sort((a, b) => a.fetched_at.localeCompare(b.fetched_at));
  const inRange = query.since ? sorted.filter((s) => s.fetched_at >= (query.since as string)) : sorted;
  /* Die jüngsten limit Messungen, chronologisch */
  const series = inRange.slice(-query.limit).map(serializeSnapshot);
  const windows = feedback
    .filter((f) => f.publication_id === publicationId)
    .sort((a, b) => WINDOW_ORDER.indexOf(a.metric_window) - WINDOW_ORDER.indexOf(b.metric_window))
    .map(serializeWindow);
  return {
    publication_id: publicationId,
    latest: latestSnapshot(sorted),
    windows,
    series,
    series_total: inRange.length,
    ...detectAnomaly(sorted.map(serializeSnapshot)),
  };
}
