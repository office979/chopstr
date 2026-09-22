import { DEFAULT_CAPABILITIES } from "@/lib/publishing/capabilities";
import type { Credentials, MetricWindow } from "@/lib/repo/types-publishing";
import { bearer, expiresAtFrom, getJson, postForm, putBytes } from "./http";
import { NotConfiguredError, ProviderError, type Provider, type PublishResult } from "./types";

/* YouTube Data API v3 (videos.insert, resumable) und YouTube Analytics API. Env YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET.
 * Shorts: vertikales Video bis 3 Minuten wird automatisch als Short eingeordnet; „#Shorts“ in Titel oder Beschreibung
 * gilt als Hinweis. Alle Endpunkte: TODO verify against current docs (developers.google.com/youtube, CON-007). */

const AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"; // TODO verify against current docs
const TOKEN_URL = "https://oauth2.googleapis.com/token"; // TODO verify against current docs
const CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"; // TODO verify against current docs
const UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"; // TODO verify against current docs
const VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"; // TODO verify against current docs
const ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"; // TODO verify against current docs
const SCOPES = [
  "https://www.googleapis.com/auth/youtube.upload",
  "https://www.googleapis.com/auth/youtube.readonly",
  "https://www.googleapis.com/auth/yt-analytics.readonly",
].join(" "); // TODO verify against current docs

function env() {
  return { id: process.env.YOUTUBE_CLIENT_ID?.trim() ?? "", secret: process.env.YOUTUBE_CLIENT_SECRET?.trim() ?? "" };
}

interface Token {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  scope?: string;
  error?: string;
  error_description?: string;
}

export const youtubeProvider: Provider = {
  platform: "youtube",
  label: "YouTube",
  configured: () => Boolean(env().id && env().secret),
  capabilities: () => ({ ...DEFAULT_CAPABILITIES.youtube }),

  authorizeUrl(state, redirectUri) {
    const { id } = env();
    if (!id) throw new NotConfiguredError("YouTube");
    const q = new URLSearchParams({ client_id: id, redirect_uri: redirectUri, response_type: "code", scope: SCOPES, access_type: "offline", prompt: "consent", include_granted_scopes: "true", state });
    return `${AUTH_URL}?${q.toString()}`;
  },

  async exchangeCode(code, redirectUri) {
    const { id, secret } = env();
    if (!id || !secret) throw new NotConfiguredError("YouTube");
    const tok = await postForm<Token>(TOKEN_URL, { code, client_id: id, client_secret: secret, redirect_uri: redirectUri, grant_type: "authorization_code" }, {}, "Google Token");
    if (!tok.access_token) throw new ProviderError(`Google Token: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    const creds: Credentials = { access_token: tok.access_token, refresh_token: tok.refresh_token, expires_at: expiresAtFrom(tok.expires_in), scope: tok.scope };
    let label = "YouTube-Kanal";
    let channelId: string | null = null;
    try {
      const ch = await getJson<{ items?: { id: string; snippet?: { title?: string } }[] }>(CHANNELS_URL, bearer(creds.access_token), "YouTube Kanal");
      channelId = ch.items?.[0]?.id ?? null;
      label = ch.items?.[0]?.snippet?.title ?? label;
      creds.channel_id = channelId ?? undefined;
    } catch {
      /* Label bleibt generisch */
    }
    return { credentials: creds, account_label: label, external_account_id: channelId, expires_at: creds.expires_at ?? null };
  },

  async refresh(creds) {
    const { id, secret } = env();
    if (!id || !secret) throw new NotConfiguredError("YouTube");
    if (!creds.refresh_token) throw new ProviderError("YouTube: kein refresh_token vorhanden, bitte neu verbinden (prompt=consent).");
    const tok = await postForm<Token>(TOKEN_URL, { client_id: id, client_secret: secret, refresh_token: creds.refresh_token, grant_type: "refresh_token" }, {}, "Google Refresh");
    if (!tok.access_token) throw new ProviderError(`Google Refresh: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    return { ...creds, access_token: tok.access_token, expires_at: expiresAtFrom(tok.expires_in) };
  },

  async publish(creds, input): Promise<PublishResult> {
    const bytes = await input.loadVideo();
    if (!bytes) return { status: "failed", external_id: null, external_url: null, error: "Videodatei nicht im Objektspeicher gefunden." };
    const title = (input.title || input.caption.split("\n")[0] || "Short").slice(0, 100);
    const description = input.caption.includes("#Shorts") ? input.caption : `${input.caption}\n\n#Shorts`.trim();
    const body = {
      snippet: { title, description: description.slice(0, 5000), categoryId: "22" },
      status: { privacyStatus: process.env.YOUTUBE_PRIVACY_STATUS ?? "public", selfDeclaredMadeForKids: false },
    }; // TODO verify against current docs
    const init = await fetch(UPLOAD_URL, {
      method: "POST",
      headers: { ...bearer(creds.access_token), "Content-Type": "application/json; charset=UTF-8", "X-Upload-Content-Length": String(bytes.length), "X-Upload-Content-Type": "video/mp4" },
      body: JSON.stringify(body),
    });
    if (!init.ok) return { status: "failed", external_id: null, external_url: null, error: `YouTube Upload-Start antwortete mit ${init.status}` };
    const location = init.headers.get("location");
    if (!location) return { status: "failed", external_id: null, external_url: null, error: "YouTube lieferte keine Upload-Session." };
    const up = await putBytes(location, bytes, { "Content-Type": "video/mp4", "Content-Length": String(bytes.length) }, "YouTube Upload");
    let videoId: string | null = null;
    try {
      const data = (await up.json()) as { id?: string };
      videoId = data.id ?? null;
    } catch {
      /* 308 oder leerer Body */
    }
    if (!videoId) return { status: "failed", external_id: null, external_url: null, error: "YouTube lieferte keine Video-ID." };
    return { status: "published", external_id: videoId, external_url: `https://www.youtube.com/shorts/${videoId}`, error: null };
  },

  async fetchMetrics(creds, externalId, window: MetricWindow) {
    const headers = bearer(creds.access_token);
    const stats = await getJson<{ items?: { statistics?: { viewCount?: string; likeCount?: string; commentCount?: string } }[] }>(`${VIDEOS_URL}?part=statistics&id=${encodeURIComponent(externalId)}`, headers, "YouTube Statistik"); // TODO verify against current docs
    const s = stats.items?.[0]?.statistics;
    const n = (v: string | undefined) => (v != null && Number.isFinite(Number(v)) ? Number(v) : null);
    const out: Record<string, number | null> = { views: n(s?.viewCount), likes: n(s?.likeCount), comments: n(s?.commentCount) };
    /* Analytics: Shares, Sehdauer und gewonnene Abonnenten seit Veröffentlichung (Zeitfenster grob über das Datum) */
    try {
      const days = window === "6h" ? 1 : window === "48h" ? 2 : 7;
      const end = new Date();
      const start = new Date(end.getTime() - days * 86_400_000);
      const iso = (d: Date) => d.toISOString().slice(0, 10);
      const q = new URLSearchParams({ ids: "channel==MINE", startDate: iso(start), endDate: iso(end), metrics: "shares,averageViewDuration,subscribersGained", filters: `video==${externalId}` });
      const a = await getJson<{ columnHeaders?: { name: string }[]; rows?: (number | string)[][] }>(`${ANALYTICS_URL}?${q.toString()}`, headers, "YouTube Analytics"); // TODO verify against current docs
      const row = a.rows?.[0];
      if (row && a.columnHeaders) {
        const idx = (name: string) => a.columnHeaders!.findIndex((h) => h.name === name);
        const pick = (name: string) => {
          const i = idx(name);
          const v = i >= 0 ? Number(row[i]) : NaN;
          return Number.isFinite(v) ? v : null;
        };
        out.shares = pick("shares");
        out.avg_watch_time_s = pick("averageViewDuration");
        out.follows = pick("subscribersGained");
      }
    } catch {
      /* Analytics optional (Scope oder Verzögerung), Felder bleiben null */
    }
    return out;
  },
};
