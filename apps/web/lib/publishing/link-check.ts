import { isLinkError, type LinkKind, type LinkPlatform, type ParseResult } from "./links";
import type { PublicMetricSet, PublicMetricSource, PublicMetricsResult } from "./public-metrics";

/* Linktest (POST /api/v1/links/test und das Eintragen eines Links am Clip).
 *
 * Die Prüfungen orientieren sich an dem, was Clipping-Plattformen vor einer Auszahlung prüfen: ist der
 * Link ein einzelner Beitrag, ist er öffentlich erreichbar, gehört er einem verbundenen Konto, wird er
 * schon gezählt, wie alt ist er, gibt es Zahlen. Die Logik ist rein; Netz und Datenbank kommen über
 * LinkCheckDeps herein, damit die Route dünn bleibt und der Test ohne beides läuft. */

export interface LinkCheckConnection {
  id: string;
  platform: string;
  account_label: string;
  external_account_id: string | null;
  status: string;
}

export interface LinkCheckDeps {
  resolve: (url: string) => Promise<ParseResult>;
  readPublic: (platform: LinkPlatform, externalId: string) => Promise<PublicMetricsResult>;
  listConnections: () => Promise<LinkCheckConnection[]>;
  findDuplicate: (platform: LinkPlatform, externalId: string) => Promise<{ id: string } | null>;
  /* Gibt es den Beitrag? true oder false nur mit Beleg (oEmbed bei YouTube und TikTok), sonst null.
   * Nur gefragt, wenn kein öffentlicher Leser geantwortet hat. */
  probe: (platform: LinkPlatform, url: string) => Promise<boolean | null>;
  now: () => number;
}

export interface LinkChecks {
  parsed: boolean;
  /* true oder false nur mit Beleg (öffentlicher Leser oder oEmbed), null heisst „nicht geprüft“ */
  reachable: boolean | null;
  owned_by_connection: boolean;
  duplicate_publication_id: string | null;
  age_s: number | null;
  metrics_available: boolean;
}

export type LinkCheckMetrics = Pick<PublicMetricSet, "views" | "likes" | "comments" | "shares" | "saves" | "reach"> & { source: PublicMetricSource };

export interface LinkCheckResult {
  platform: LinkPlatform | null;
  external_id: string | null;
  normalized_url: string | null;
  kind: LinkKind | null;
  checks: LinkChecks;
  metrics: LinkCheckMetrics | null;
  published_at: string | null;
  author: { id: string | null; label: string | null } | null;
  /* Verbindung, der der Beitrag gehört (nur bei owned_by_connection) */
  connection_id: string | null;
  /* Lässt sich der Beitrag jetzt messen? Eingerichteter öffentlicher Leser (YouTube, X) oder eigene Verbindung */
  measurable: boolean;
  notes: string[];
}

export const DUPLICATE_MESSAGE = "Dieser Beitrag ist schon eingetragen.";

const PLATFORM_LABEL: Record<LinkPlatform, string> = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", x: "X", linkedin: "LinkedIn" };

function emptyChecks(): LinkChecks {
  return { parsed: false, reachable: null, owned_by_connection: false, duplicate_publication_id: null, age_s: null, metrics_available: false };
}

export async function runLinkCheck(url: string, deps: LinkCheckDeps): Promise<LinkCheckResult> {
  const parsed = await deps.resolve(url);
  if (isLinkError(parsed)) {
    return { platform: null, external_id: null, normalized_url: null, kind: null, checks: emptyChecks(), metrics: null, published_at: null, author: null, connection_id: null, measurable: false, notes: [parsed.message] };
  }
  const checks: LinkChecks = { ...emptyChecks(), parsed: true };
  const notes: string[] = [];
  const label = PLATFORM_LABEL[parsed.platform];
  const base = { platform: parsed.platform, external_id: parsed.externalId, normalized_url: parsed.normalizedUrl, kind: parsed.kind };

  if (parsed.kind === "short_link") {
    notes.push("Der Kurzlink ließ sich nicht auflösen. Bitte den vollständigen Link einfügen.");
    return { ...base, checks, metrics: null, published_at: null, author: null, connection_id: null, measurable: false, notes };
  }

  const [publicResult, connections, duplicate] = await Promise.all([
    deps.readPublic(parsed.platform, parsed.externalId),
    deps.listConnections().catch(() => [] as LinkCheckConnection[]),
    deps.findDuplicate(parsed.platform, parsed.externalId).catch(() => null),
  ]);

  checks.duplicate_publication_id = duplicate?.id ?? null;
  if (duplicate) notes.push(DUPLICATE_MESSAGE);

  let metrics: LinkCheckMetrics | null = null;
  let publishedAt: string | null = null;
  let author: LinkCheckResult["author"] = null;
  let connectionId: string | null = null;

  if (publicResult.ok) {
    checks.reachable = true;
    const m = publicResult.metrics;
    metrics = { views: m.views, likes: m.likes, comments: m.comments, shares: m.shares, saves: m.saves, reach: m.reach, source: publicResult.source };
    checks.metrics_available = m.views != null || m.likes != null || m.comments != null;
    publishedAt = publicResult.published_at;
    author = { id: publicResult.author_id, label: publicResult.author_label };
    const owner = publicResult.author_id
      ? connections.find((c) => c.platform === parsed.platform && c.status === "connected" && c.external_account_id === publicResult.author_id)
      : undefined;
    if (owner) {
      checks.owned_by_connection = true;
      connectionId = owner.id;
      notes.push(`Gehört zum verbundenen Konto ${owner.account_label}.`);
    } else {
      notes.push("Kein verbundenes Konto, Messwerte kommen aus öffentlichen Daten.");
    }
  } else {
    notes.push(publicResult.message);
    if (publicResult.error === "nicht_gefunden") {
      checks.reachable = false;
    } else {
      /* Ohne Antwort des Lesers (kein Schlüssel, keine Schnittstelle, Störung) nur ein Beleg zählt: oEmbed.
       * Wo es keinen gibt, bleibt reachable null und es kommt kein „nicht bestätigt“. */
      checks.reachable = await deps.probe(parsed.platform, parsed.normalizedUrl).catch(() => null);
      if (checks.reachable === false) notes.push(`${label} kennt diesen Beitrag nicht oder er ist nicht öffentlich.`);
    }
  }
  const readerMissing = !publicResult.ok && publicResult.error === "nicht_konfiguriert";
  const measurable = connectionId != null || (PUBLIC_READER_PLATFORMS.includes(parsed.platform) && !readerMissing);

  if (publishedAt) {
    const t = Date.parse(publishedAt);
    if (Number.isFinite(t)) checks.age_s = Math.max(0, Math.round((deps.now() - t) / 1000));
  }

  return { ...base, checks, metrics, published_at: publishedAt, author, connection_id: connectionId, measurable, notes };
}

export const DEFAULT_TRACK_DAYS = 30;
export const MAX_TRACK_DAYS = 90;

export interface LinkPublicationPlan {
  platform: LinkPlatform;
  external_id: string;
  external_url: string;
  connection_id: string | null;
  /* Zeitpunkt laut Plattform; null, wenn sie ihn nicht nennt (dann übernimmt der Worker ihn bei der ersten
   * erfolgreichen Messung, bis dahin gibt es keine festen Fenster) */
  published_at: string | null;
  tracking_until: string;
  tracking_days: number;
  /* Gerundete Tage, die ab jetzt noch gemessen werden (0: Beitrag älter als die Messdauer, eine Messung) */
  remaining_days: number;
  /* Lässt sich jetzt messen? Eingerichteter öffentlicher Leser (YouTube, X) oder eigene Verbindung.
   * Fehlt nur der Schlüssel, plant der Worker den Link nach, sobald er da ist (Modus replan der internen Route). */
  measurable: boolean;
  /* null, wenn nichts zu messen ist: dann fragt der Worker gar nicht erst */
  next_snapshot_at: string | null;
  link_check: { checks: LinkChecks; notes: string[]; metrics: LinkCheckMetrics | null; author: LinkCheckResult["author"]; checked_at: string; tracking_days: number };
}

export type LinkPlanOutcome = { ok: true; plan: LinkPublicationPlan } | { ok: false; status: 400 | 409; code: string; message: string; duplicate_publication_id?: string };

/* Plattformen mit öffentlichem Leser (lib/publishing/public-metrics.ts) */
export const PUBLIC_READER_PLATFORMS: readonly LinkPlatform[] = ["youtube", "x"];

/* Aus dem Linktest wird eine Publikation zum Verfolgen: veröffentlicht laut Plattform (sonst unbekannt), gemessen
 * bis published_at + trackDays (ohne Zeitpunkt ab jetzt), erste Messung sofort. Ohne eingerichteten öffentlichen Leser und ohne eigene
 * Verbindung (TikTok, Instagram, LinkedIn fremder Konten, YouTube oder X ohne Schlüssel) gibt es nichts zu
 * messen: dann kein Termin, statt 30 Tage lang Fehlerzeilen zu schreiben. Dubletten werden abgelehnt (409). */
export function planLinkPublication(result: LinkCheckResult, opts: { now: number; trackDays?: number }): LinkPlanOutcome {
  if (!result.checks.parsed || !result.platform || !result.external_id || !result.normalized_url) {
    return { ok: false, status: 400, code: "link_invalid", message: result.notes[0] ?? "Der Link ist ungültig." };
  }
  if (result.kind === "short_link") {
    return { ok: false, status: 400, code: "link_unresolved", message: "Der Kurzlink ließ sich nicht auflösen. Bitte den vollständigen Link einfügen." };
  }
  if (result.checks.duplicate_publication_id) {
    return { ok: false, status: 409, code: "link_duplicate", message: DUPLICATE_MESSAGE, duplicate_publication_id: result.checks.duplicate_publication_id };
  }
  const days = Math.min(MAX_TRACK_DAYS, Math.max(1, Math.round(opts.trackDays ?? DEFAULT_TRACK_DAYS)));
  const platformTime = result.published_at ? Date.parse(result.published_at) : NaN;
  /* Ohne Zeitpunkt der Plattform bleibt published_at leer und die Messdauer zählt ab jetzt; ein Zeitpunkt
   * aus der Zukunft wäre ein Uhrenfehler, dann gilt jetzt */
  const known = Number.isFinite(platformTime);
  const publishedAt = known ? Math.min(platformTime, opts.now) : null;
  const until = (publishedAt ?? opts.now) + days * 86_400_000;
  const measurable = result.measurable;
  return {
    ok: true,
    plan: {
      platform: result.platform,
      external_id: result.external_id,
      external_url: result.normalized_url,
      connection_id: result.connection_id,
      published_at: publishedAt == null ? null : new Date(publishedAt).toISOString(),
      tracking_until: new Date(until).toISOString(),
      tracking_days: days,
      remaining_days: Math.max(0, Math.round((until - opts.now) / 86_400_000)),
      measurable,
      next_snapshot_at: measurable ? new Date(opts.now).toISOString() : null,
      link_check: { checks: result.checks, notes: result.notes, metrics: result.metrics, author: result.author, checked_at: new Date(opts.now).toISOString(), tracking_days: days },
    },
  };
}

/* Kurze Sätze für die Oberfläche: was der Linktest ergeben hat. Mit plan sagt der letzte Satz, wie lange
 * wirklich gemessen wird; ohne plan gilt die Standarddauer. Ob gemessen wird, folgt aus result.measurable,
 * also aus derselben Regel wie der Messtermin. */
export function linkCheckSummary(result: LinkCheckResult, plan?: Pick<LinkPublicationPlan, "tracking_days" | "remaining_days">): string[] {
  if (!result.checks.parsed || !result.platform) return result.notes.slice(0, 1);
  const label = PLATFORM_LABEL[result.platform];
  const out = [`Link erkannt: ${label}`];
  out.push(result.checks.owned_by_connection ? "Verbundenes Konto erkannt" : "Kein verbundenes Konto");
  if (result.checks.duplicate_publication_id) out.push(DUPLICATE_MESSAGE.slice(0, -1));
  else if (!result.measurable) out.push(notMeasuredReason(result.platform));
  else if (plan && plan.remaining_days < plan.tracking_days) {
    out.push(plan.remaining_days > 0 ? `Wird noch ${plan.remaining_days} Tage lang gemessen` : `Wird einmal gemessen, der Beitrag ist älter als ${plan.tracking_days} Tage`);
  } else out.push(`Wird ${plan?.tracking_days ?? DEFAULT_TRACK_DAYS} Tage lang gemessen`);
  return out;
}

/* Warum ein Link nicht gemessen wird, in Klartext (Oberfläche und Zusammenfassung) */
export function notMeasuredReason(platform: LinkPlatform): string {
  return PUBLIC_READER_PLATFORMS.includes(platform)
    ? `Zahlen für ${PLATFORM_LABEL[platform]} sind noch nicht eingerichtet, gemessen wird, sobald das erledigt ist`
    : `Wird nicht gemessen: ${PLATFORM_LABEL[platform]} braucht ein verbundenes Konto`;
}

/* publications.platform mischt zwei Wertebereiche, bewusst nicht vereinheitlicht (bestehende Daten):
 *   - Schnittformat des Clips (clips.platform: tiktok, reels, shorts, linkedin) bei Publikationen über
 *     „Als gepostet eintragen“ ohne Link und bei OAuth-Publikationen (publish/route.ts setzt ctx.clip.platform);
 *   - Link-Plattform (youtube, tiktok, instagram, x, linkedin) bei Publikationen aus einem Link (tracking link).
 * Für die Dublettenprüfung zählen deshalb alle Werte, unter denen derselbe Beitrag stehen kann. */
const PUBLICATION_PLATFORM_ALIASES: Record<LinkPlatform, readonly string[]> = {
  youtube: ["youtube", "shorts"],
  instagram: ["instagram", "reels"],
  tiktok: ["tiktok"],
  linkedin: ["linkedin"],
  x: ["x"],
};

export function publicationPlatformsFor(platform: LinkPlatform): string[] {
  return [...PUBLICATION_PLATFORM_ALIASES[platform]];
}

/* Clip-Plattform (Schnittformat) ↔ Link-Plattform. X hat kein eigenes Format, jedes passt. */
const CLIP_FORMAT_PLATFORM: Record<string, LinkPlatform> = { shorts: "youtube", reels: "instagram", tiktok: "tiktok", linkedin: "linkedin" };
const CLIP_FORMAT_LABEL: Record<string, string> = { shorts: "YouTube Shorts", reels: "Instagram Reels", tiktok: "TikTok", linkedin: "LinkedIn" };

export function clipFormatHint(linkPlatform: LinkPlatform | null, clipPlatform: string | null | undefined): string | null {
  if (!linkPlatform || !clipPlatform || linkPlatform === "x") return null;
  const expected = CLIP_FORMAT_PLATFORM[clipPlatform];
  if (!expected || expected === linkPlatform) return null;
  return `Der Clip ist für ${CLIP_FORMAT_LABEL[clipPlatform]} geschnitten, der Link führt zu ${PLATFORM_LABEL[linkPlatform]}.`;
}

const PROBE_TIMEOUT_MS = 5_000;

/* oEmbed-Endpunkte, die für unbekannte Beiträge 404 oder 400 liefern. TODO verify against current docs. */
const OEMBED_URL: Partial<Record<LinkPlatform, string>> = {
  youtube: "https://www.youtube.com/oembed",
  tiktok: "https://www.tiktok.com/oembed",
};

/* Gibt es den Beitrag? oEmbed bei YouTube und TikTok (200: ja, 400 oder 404: nein), sonst und bei jeder
 * anderen Antwort null („nicht geprüft“). Eine Plattformseite mit 200 ist kein Beleg: TikTok, Instagram und
 * LinkedIn liefern 200 auch für Beiträge, die es nicht gibt. 5 s Timeout. */
export async function probeOembed(platform: LinkPlatform, url: string, fetchImpl: typeof fetch = fetch): Promise<boolean | null> {
  const endpoint = OEMBED_URL[platform];
  if (!endpoint) return null;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const q = new URLSearchParams({ url, format: "json" });
    const res = await fetchImpl(`${endpoint}?${q.toString()}`, { method: "GET", redirect: "follow", signal: ctrl.signal, headers: { "User-Agent": "chopstr-linktest/1.0" } });
    if (res.status === 200) return true;
    if (res.status === 404 || res.status === 400) return false;
    return null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
