/* Linkparser für Plattform-URLs (Linktest und Link-Tracking). Rein, ohne Server-Abhängigkeiten:
 * aus einer eingefügten URL werden Plattform, externe ID und eine bereinigte URL ohne Tracking-Parameter.
 *
 * Kurzlinks von TikTok (vm.tiktok.com, vt.tiktok.com) tragen die Video-ID nicht in sich. parsePostUrl
 * erkennt sie als kind "short_link"; resolvePostUrl folgt dann genau einer Weiterleitung (5 s Timeout)
 * und parst das Ziel. LinkedIn wird nur geparst, Messwerte gibt es dort ohne Verbindung nicht. */

export type LinkPlatform = "youtube" | "tiktok" | "instagram" | "x" | "linkedin";
export type LinkKind = "short" | "video" | "reel" | "post" | "status" | "short_link";

export interface ParsedLink {
  platform: LinkPlatform;
  externalId: string;
  normalizedUrl: string;
  kind: LinkKind;
}

export type LinkErrorCode = "leer" | "keine_url" | "unbekannte_plattform" | "keine_id";

export interface LinkError {
  error: LinkErrorCode;
  message: string;
}

export type ParseResult = ParsedLink | LinkError;

export function isLinkError(r: ParseResult): r is LinkError {
  return "error" in r;
}

const ERROR_MESSAGES: Record<LinkErrorCode, string> = {
  leer: "Kein Link angegeben.",
  keine_url: "Das ist kein gültiger Link.",
  unbekannte_plattform: "Diese Plattform wird nicht unterstützt. Möglich sind YouTube, TikTok, Instagram, X und LinkedIn.",
  keine_id: "Im Link steht kein einzelner Beitrag.",
};

function fail(error: LinkErrorCode): LinkError {
  return { error, message: ERROR_MESSAGES[error] };
}

const YT_ID = /^[A-Za-z0-9_-]{11}$/;
const TIKTOK_ID = /^\d{8,25}$/;
const IG_CODE = /^[A-Za-z0-9_-]{5,40}$/;
const X_ID = /^\d{1,25}$/;
/* Einbett-Spiegel, die Clipper oft teilen; sie zeigen denselben Beitrag wie x.com */
const X_HOSTS = new Set(["x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com"]);
const X_USER = /^[A-Za-z0-9_]{1,15}$/;

function hostOf(url: URL): string {
  return url.hostname.toLowerCase().replace(/^(www\.|m\.|mobile\.)/, "");
}

function segments(url: URL): string[] {
  return url.pathname.split("/").filter(Boolean);
}

function toUrl(raw: string): URL | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    if (!url.hostname.includes(".")) return null;
    return url;
  } catch {
    return null;
  }
}

function parseYoutube(url: URL, host: string): ParseResult {
  const segs = segments(url);
  if (host === "youtu.be") {
    const id = segs[0] ?? "";
    return YT_ID.test(id) ? { platform: "youtube", externalId: id, normalizedUrl: `https://www.youtube.com/watch?v=${id}`, kind: "video" } : fail("keine_id");
  }
  if (segs[0] === "shorts" || segs[0] === "live" || segs[0] === "embed") {
    const id = segs[1] ?? "";
    if (!YT_ID.test(id)) return fail("keine_id");
    return segs[0] === "shorts"
      ? { platform: "youtube", externalId: id, normalizedUrl: `https://www.youtube.com/shorts/${id}`, kind: "short" }
      : { platform: "youtube", externalId: id, normalizedUrl: `https://www.youtube.com/watch?v=${id}`, kind: "video" };
  }
  if (segs[0] === "watch") {
    const id = url.searchParams.get("v") ?? "";
    return YT_ID.test(id) ? { platform: "youtube", externalId: id, normalizedUrl: `https://www.youtube.com/watch?v=${id}`, kind: "video" } : fail("keine_id");
  }
  return fail("keine_id");
}

function parseTiktok(url: URL, host: string): ParseResult {
  const segs = segments(url);
  if (host === "vm.tiktok.com" || host === "vt.tiktok.com") {
    const code = segs[0] ?? "";
    if (!/^[A-Za-z0-9]{4,20}$/.test(code)) return fail("keine_id");
    return { platform: "tiktok", externalId: code, normalizedUrl: `https://${host}/${code}/`, kind: "short_link" };
  }
  if (host === "tiktok.com" && segs[0] === "t" && segs[1]) {
    /* tiktok.com/t/CODE ist ebenfalls ein Kurzlink */
    return { platform: "tiktok", externalId: segs[1], normalizedUrl: `https://www.tiktok.com/t/${segs[1]}/`, kind: "short_link" };
  }
  const user = segs[0] ?? "";
  if (user.startsWith("@") && (segs[1] === "video" || segs[1] === "photo")) {
    const id = segs[2] ?? "";
    if (!TIKTOK_ID.test(id)) return fail("keine_id");
    return { platform: "tiktok", externalId: id, normalizedUrl: `https://www.tiktok.com/${user}/${segs[1]}/${id}`, kind: "video" };
  }
  return fail("keine_id");
}

function parseInstagram(url: URL): ParseResult {
  const segs = segments(url);
  /* Profil-Präfix erlaubt: instagram.com/<user>/reel/CODE */
  const i = segs.findIndex((s) => s === "reel" || s === "reels" || s === "p" || s === "tv");
  if (i < 0) return fail("keine_id");
  const code = segs[i + 1] ?? "";
  if (!IG_CODE.test(code)) return fail("keine_id");
  const isPost = segs[i] === "p";
  return {
    platform: "instagram",
    externalId: code,
    normalizedUrl: `https://www.instagram.com/${isPost ? "p" : "reel"}/${code}/`,
    kind: isPost ? "post" : "reel",
  };
}

function parseX(url: URL): ParseResult {
  const segs = segments(url);
  if (segs[0] === "i" && segs[1] === "status") {
    const id = segs[2] ?? "";
    return X_ID.test(id) ? { platform: "x", externalId: id, normalizedUrl: `https://x.com/i/status/${id}`, kind: "status" } : fail("keine_id");
  }
  if (segs[0] === "i" && segs[1] === "web" && segs[2] === "status") {
    const id = segs[3] ?? "";
    return X_ID.test(id) ? { platform: "x", externalId: id, normalizedUrl: `https://x.com/i/status/${id}`, kind: "status" } : fail("keine_id");
  }
  const user = segs[0] ?? "";
  if (X_USER.test(user) && segs[1] === "status") {
    const id = segs[2] ?? "";
    return X_ID.test(id) ? { platform: "x", externalId: id, normalizedUrl: `https://x.com/${user}/status/${id}`, kind: "status" } : fail("keine_id");
  }
  return fail("keine_id");
}

function parseLinkedin(url: URL): ParseResult {
  const segs = segments(url);
  if (segs[0] === "posts" && segs[1]) {
    /* linkedin.com/posts/<slug>-activity-<id>-<suffix>; ohne activity-ID kein eindeutiger Beitrag (ein Slug
     * allein ist keine ID und würde Dubletten und Messung an einen beliebigen Text hängen) */
    const m = /activity[-:](\d{10,25})/.exec(segs[1]);
    if (!m) return fail("keine_id");
    return { platform: "linkedin", externalId: `urn:li:activity:${m[1]}`, normalizedUrl: `https://www.linkedin.com/posts/${segs[1]}/`, kind: "post" };
  }
  if (segs[0] === "feed" && segs[1] === "update" && segs[2]) {
    const urn = decodeURIComponent(segs[2]);
    if (!/^urn:li:(activity|share|ugcPost):\d{5,25}$/.test(urn)) return fail("keine_id");
    return { platform: "linkedin", externalId: urn, normalizedUrl: `https://www.linkedin.com/feed/update/${urn}/`, kind: "post" };
  }
  return fail("keine_id");
}

/* Plattform-URL zerlegen. Tracking-Parameter (utm_*, si, igsh, feature, s, t …) fallen weg, weil die
 * bereinigte URL aus der ID neu gebaut wird; nur was die ID trägt, bleibt übrig. */
export function parsePostUrl(raw: string | null | undefined): ParseResult {
  if (raw == null || !String(raw).trim()) return fail("leer");
  const url = toUrl(String(raw));
  if (!url) return fail("keine_url");
  const host = hostOf(url);
  if (host === "youtube.com" || host === "youtu.be" || host === "music.youtube.com") return parseYoutube(url, host);
  if (host === "tiktok.com" || host === "vm.tiktok.com" || host === "vt.tiktok.com") return parseTiktok(url, host);
  if (host === "instagram.com") return parseInstagram(url);
  if (X_HOSTS.has(host)) return parseX(url);
  if (host === "linkedin.com") return parseLinkedin(url);
  return fail("unbekannte_plattform");
}

const RESOLVE_TIMEOUT_MS = 5_000;

/* Wie parsePostUrl, folgt bei TikTok-Kurzlinks aber genau einer Weiterleitung. fetchImpl ist für Tests
 * austauschbar. Scheitert die Auflösung, kommt der Kurzlink unverändert zurück (kind "short_link"). */
export async function resolvePostUrl(raw: string, fetchImpl: typeof fetch = fetch): Promise<ParseResult> {
  const first = parsePostUrl(raw);
  if (isLinkError(first) || first.kind !== "short_link") return first;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), RESOLVE_TIMEOUT_MS);
  try {
    const res = await fetchImpl(first.normalizedUrl, { method: "HEAD", redirect: "manual", signal: ctrl.signal });
    const location = res.headers.get("location");
    if (!location) return first;
    const target = parsePostUrl(new URL(location, first.normalizedUrl).toString());
    return isLinkError(target) || target.kind === "short_link" ? first : target;
  } catch {
    return first;
  } finally {
    clearTimeout(timer);
  }
}
