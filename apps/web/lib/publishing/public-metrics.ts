import type { MetricSet } from "@/lib/repo/types-publishing";
import type { LinkPlatform } from "./links";

/* Öffentliche Messwerte ohne verbundenes Konto (Linktest und Link-Tracking).
 *
 * Nur YouTube und X geben Zahlen zu fremden oder nicht verbundenen Beiträgen über eine offizielle
 * Schnittstelle heraus:
 *   YouTube Data API v3 videos.list mit API-Schlüssel (YOUTUBE_API_KEY), 1 Quota-Einheit je Abruf.
 *   X API v2 GET /2/tweets/:id mit App-Bearer (X_BEARER_TOKEN), Abrechnung je gelesenem Beitrag,
 *   deshalb hier eine Stunde Cache je ID.
 * TikTok und Instagram liefern Zahlen nur über ein verbundenes Konto (die bestehenden Provider);
 * ohne Verbindung kommt "nicht_verbunden" zurück. Ein Scraper-Anbieter ist bewusst nicht angebunden
 * (PUBLIC_METRICS_SCRAPER, US-Anbieter, im Sovereign-Tarif nicht zulässig).
 *
 * Fehlende Schlüssel werfen nie: das Ergebnis ist dann { ok: false, error: "nicht_konfiguriert" } mit
 * einer deutschen Meldung. Endpunkte: TODO verify against current docs (CON-007). */

export const YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"; // TODO verify against current docs
export const X_TWEETS_URL = "https://api.x.com/2/tweets"; // TODO verify against current docs

export type PublicMetricSource = "public_api" | "scraper" | "oauth";

export interface PublicMetricSet extends MetricSet {
  engaged_views: number | null;
  reach: number | null;
  skip_rate: number | null;
}

export interface PublicMetricsOk {
  ok: true;
  platform: LinkPlatform;
  metrics: PublicMetricSet;
  source: PublicMetricSource;
  /* Zeitpunkt der Veröffentlichung laut Plattform (ISO), wenn bekannt */
  published_at: string | null;
  /* Kanal- oder Autor-ID laut Plattform; damit prüft der Linktest, ob der Beitrag einer Verbindung gehört */
  author_id: string | null;
  author_label: string | null;
  raw: unknown;
  cached?: boolean;
}

export type PublicMetricsErrorCode = "nicht_konfiguriert" | "nicht_verbunden" | "nicht_gefunden" | "fehler";

export interface PublicMetricsFail {
  ok: false;
  platform: LinkPlatform;
  error: PublicMetricsErrorCode;
  message: string;
}

export type PublicMetricsResult = PublicMetricsOk | PublicMetricsFail;

export interface PublicMetricsOptions {
  fetchImpl?: typeof fetch;
  env?: Record<string, string | undefined>;
  now?: () => number;
  timeoutMs?: number;
}

export function emptyPublicMetrics(): PublicMetricSet {
  return {
    views: null,
    likes: null,
    comments: null,
    shares: null,
    saves: null,
    follows: null,
    avg_watch_time_s: null,
    retention_curve: null,
    engaged_views: null,
    reach: null,
    skip_rate: null,
  };
}

const PLATFORM_LABEL: Record<LinkPlatform, string> = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", x: "X", linkedin: "LinkedIn" };

function fail(platform: LinkPlatform, error: PublicMetricsErrorCode, message: string): PublicMetricsFail {
  return { ok: false, platform, error, message };
}

function count(v: unknown): number | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function sum(...values: (number | null)[]): number | null {
  const present = values.filter((v): v is number => v != null);
  return present.length ? present.reduce((a, b) => a + b, 0) : null;
}

async function getWithTimeout(fetchImpl: typeof fetch, url: string, headers: Record<string, string>, timeoutMs: number): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetchImpl(url, { method: "GET", headers, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

/* Statusmeldung ohne Schlüssel: der Body wird gekürzt und auf key= / Bearer geprüft */
function safeStatus(what: string, status: number, body: string): string {
  const snippet = body.replace(/(key=)[^&\s"]+/gi, "$1[redacted]").replace(/Bearer\s+\S+/gi, "Bearer [redacted]").slice(0, 200);
  return `${what} antwortete mit ${status}${snippet ? `: ${snippet}` : ""}`;
}

interface YoutubeVideosResponse {
  items?: {
    id?: string;
    snippet?: { publishedAt?: string; channelId?: string; channelTitle?: string; title?: string };
    statistics?: { viewCount?: string; likeCount?: string; commentCount?: string; favoriteCount?: string };
    contentDetails?: { duration?: string };
  }[];
}

async function readYoutube(externalId: string, opts: Required<PublicMetricsOptions>): Promise<PublicMetricsResult> {
  const key = opts.env.YOUTUBE_API_KEY?.trim();
  if (!key) return fail("youtube", "nicht_konfiguriert", "YouTube ist nicht konfiguriert: YOUTUBE_API_KEY fehlt.");
  const q = new URLSearchParams({ part: "statistics,snippet,contentDetails", id: externalId, key });
  let res: Response;
  try {
    res = await getWithTimeout(opts.fetchImpl, `${YOUTUBE_VIDEOS_URL}?${q.toString()}`, {}, opts.timeoutMs);
  } catch (error) {
    return fail("youtube", "fehler", `YouTube nicht erreichbar: ${error instanceof Error ? error.message : String(error)}`);
  }
  const text = await res.text();
  if (!res.ok) return fail("youtube", "fehler", safeStatus("YouTube", res.status, text));
  let data: YoutubeVideosResponse;
  try {
    data = (text ? JSON.parse(text) : {}) as YoutubeVideosResponse;
  } catch {
    return fail("youtube", "fehler", "YouTube lieferte kein JSON.");
  }
  const item = data.items?.[0];
  if (!item) return fail("youtube", "nicht_gefunden", "YouTube kennt dieses Video nicht oder es ist nicht öffentlich.");
  const s = item.statistics ?? {};
  const metrics = { ...emptyPublicMetrics(), views: count(s.viewCount), likes: count(s.likeCount), comments: count(s.commentCount) };
  return {
    ok: true,
    platform: "youtube",
    metrics,
    source: "public_api",
    published_at: item.snippet?.publishedAt ?? null,
    author_id: item.snippet?.channelId ?? null,
    author_label: item.snippet?.channelTitle ?? null,
    raw: item,
  };
}

interface XTweetResponse {
  data?: {
    id?: string;
    author_id?: string;
    created_at?: string;
    public_metrics?: { retweet_count?: number; reply_count?: number; like_count?: number; quote_count?: number; bookmark_count?: number; impression_count?: number };
    attachments?: { media_keys?: string[] };
  };
  includes?: { media?: { media_key?: string; type?: string; public_metrics?: { view_count?: number } }[]; users?: { id?: string; username?: string }[] };
  errors?: { title?: string; detail?: string; type?: string }[];
}

/* X rechnet je gelesenem Beitrag ab: Cache je ID (nur erfolgreiche Antworten). Etwas kürzer als eine Stunde,
 * damit die stündliche Messung des Workers nie die Zahlen der vorigen Stunde bekommt. */
export const X_CACHE_TTL_MS = 55 * 60 * 1000;
const xCache = new Map<string, { at: number; result: PublicMetricsOk }>();

export function clearPublicMetricsCache(): void {
  xCache.clear();
}

async function readX(externalId: string, opts: Required<PublicMetricsOptions>): Promise<PublicMetricsResult> {
  const token = opts.env.X_BEARER_TOKEN?.trim();
  if (!token) return fail("x", "nicht_konfiguriert", "X ist nicht konfiguriert: X_BEARER_TOKEN fehlt.");
  const hit = xCache.get(externalId);
  if (hit && opts.now() - hit.at < X_CACHE_TTL_MS) return { ...hit.result, cached: true };
  const q = new URLSearchParams({
    "tweet.fields": "public_metrics,created_at,author_id",
    expansions: "attachments.media_keys,author_id",
    "media.fields": "public_metrics,type",
    "user.fields": "username",
  });
  let res: Response;
  try {
    res = await getWithTimeout(opts.fetchImpl, `${X_TWEETS_URL}/${encodeURIComponent(externalId)}?${q.toString()}`, { Authorization: `Bearer ${token}` }, opts.timeoutMs);
  } catch (error) {
    return fail("x", "fehler", `X nicht erreichbar: ${error instanceof Error ? error.message : String(error)}`);
  }
  const text = await res.text();
  if (res.status === 404) return fail("x", "nicht_gefunden", "X kennt diesen Beitrag nicht oder er ist nicht öffentlich.");
  if (!res.ok) return fail("x", "fehler", safeStatus("X", res.status, text));
  let data: XTweetResponse;
  try {
    data = (text ? JSON.parse(text) : {}) as XTweetResponse;
  } catch {
    return fail("x", "fehler", "X lieferte kein JSON.");
  }
  if (!data.data) return fail("x", "nicht_gefunden", "X kennt diesen Beitrag nicht oder er ist nicht öffentlich.");
  const pm = data.data.public_metrics ?? {};
  /* Videoaufrufe stehen am Medium (includes.media[].public_metrics.view_count), Impressionen am Beitrag */
  const keys = new Set(data.data.attachments?.media_keys ?? []);
  const video = (data.includes?.media ?? []).find((m) => (!keys.size || keys.has(m.media_key ?? "")) && m.public_metrics?.view_count != null);
  const impressions = count(pm.impression_count);
  const metrics: PublicMetricSet = {
    ...emptyPublicMetrics(),
    views: count(video?.public_metrics?.view_count) ?? impressions,
    reach: impressions,
    likes: count(pm.like_count),
    comments: count(pm.reply_count),
    shares: sum(count(pm.retweet_count), count(pm.quote_count)),
    saves: count(pm.bookmark_count),
  };
  const author = data.includes?.users?.find((u) => u.id === data.data?.author_id);
  const result: PublicMetricsOk = {
    ok: true,
    platform: "x",
    metrics,
    source: "public_api",
    published_at: data.data.created_at ?? null,
    author_id: data.data.author_id ?? null,
    author_label: author?.username ? `@${author.username}` : null,
    raw: data,
  };
  xCache.set(externalId, { at: opts.now(), result });
  return result;
}

/* Öffentliche Messwerte eines Beitrags. Wirft nie; Fehler kommen als { ok: false, error, message }. */
export async function readPublicMetrics(platform: LinkPlatform, externalId: string, options: PublicMetricsOptions = {}): Promise<PublicMetricsResult> {
  const opts: Required<PublicMetricsOptions> = {
    fetchImpl: options.fetchImpl ?? fetch,
    env: options.env ?? process.env,
    now: options.now ?? Date.now,
    timeoutMs: options.timeoutMs ?? Number(process.env.PUBLISH_HTTP_TIMEOUT_MS ?? 15_000),
  };
  try {
    if (platform === "youtube") return await readYoutube(externalId, opts);
    if (platform === "x") return await readX(externalId, opts);
  } catch (error) {
    return fail(platform, "fehler", `${PLATFORM_LABEL[platform]}: ${error instanceof Error ? error.message : String(error)}`);
  }
  return fail(platform, "nicht_verbunden", `${PLATFORM_LABEL[platform]} gibt Messwerte nur über ein verbundenes Konto heraus.`);
}
