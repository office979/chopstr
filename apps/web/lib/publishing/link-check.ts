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
  /* HTTP 200 auf der bereinigten URL; nur gefragt, wenn kein öffentlicher Leser Zahlen liefert */
  probe: (url: string) => Promise<boolean>;
  now: () => number;
}

export interface LinkChecks {
  parsed: boolean;
  reachable: boolean;
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
  hinweise: string[];
}

const PLATFORM_LABEL: Record<LinkPlatform, string> = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", x: "X", linkedin: "LinkedIn" };

function emptyChecks(): LinkChecks {
  return { parsed: false, reachable: false, owned_by_connection: false, duplicate_publication_id: null, age_s: null, metrics_available: false };
}

export async function runLinkCheck(url: string, deps: LinkCheckDeps): Promise<LinkCheckResult> {
  const parsed = await deps.resolve(url);
  if (isLinkError(parsed)) {
    return { platform: null, external_id: null, normalized_url: null, kind: null, checks: emptyChecks(), metrics: null, published_at: null, author: null, connection_id: null, hinweise: [parsed.message] };
  }
  const checks: LinkChecks = { ...emptyChecks(), parsed: true };
  const hinweise: string[] = [];
  const label = PLATFORM_LABEL[parsed.platform];
  const base = { platform: parsed.platform, external_id: parsed.externalId, normalized_url: parsed.normalizedUrl, kind: parsed.kind };

  if (parsed.kind === "short_link") {
    hinweise.push("Der Kurzlink ließ sich nicht auflösen. Bitte den vollständigen Link einfügen.");
    return { ...base, checks, metrics: null, published_at: null, author: null, connection_id: null, hinweise };
  }

  const [publicResult, connections, duplicate] = await Promise.all([
    deps.readPublic(parsed.platform, parsed.externalId),
    deps.listConnections().catch(() => [] as LinkCheckConnection[]),
    deps.findDuplicate(parsed.platform, parsed.externalId).catch(() => null),
  ]);

  checks.duplicate_publication_id = duplicate?.id ?? null;
  if (duplicate) hinweise.push("Dieser Beitrag wird schon verfolgt.");

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
      hinweise.push(`Gehört zum verbundenen Konto ${owner.account_label}.`);
    } else {
      hinweise.push("Kein verbundenes Konto, Messwerte kommen aus öffentlichen Daten.");
    }
  } else {
    hinweise.push(publicResult.message);
    if (publicResult.error === "nicht_gefunden") {
      checks.reachable = false;
    } else {
      checks.reachable = await deps.probe(parsed.normalizedUrl).catch(() => false);
      if (!checks.reachable) hinweise.push(`${label} hat den Link nicht bestätigt. Ist der Beitrag öffentlich?`);
    }
  }

  if (publishedAt) {
    const t = Date.parse(publishedAt);
    if (Number.isFinite(t)) checks.age_s = Math.max(0, Math.round((deps.now() - t) / 1000));
  }

  return { ...base, checks, metrics, published_at: publishedAt, author, connection_id: connectionId, hinweise };
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

/* Erreichbarkeit per GET auf die bereinigte URL (folgt Weiterleitungen), 5 s Timeout */
export async function probeUrl(url: string, fetchImpl: typeof fetch = fetch): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
  try {
    const res = await fetchImpl(url, { method: "GET", redirect: "follow", signal: ctrl.signal, headers: { "User-Agent": "chopstr-linktest/1.0" } });
    return res.status === 200;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
