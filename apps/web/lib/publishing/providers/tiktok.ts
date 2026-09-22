import { DEFAULT_CAPABILITIES } from "@/lib/publishing/capabilities";
import type { Credentials } from "@/lib/repo/types-publishing";
import { bearer, expiresAtFrom, getJson, postForm, postJson, putBytes, sleep } from "./http";
import { NotConfiguredError, ProviderError, type Provider, type PublishResult } from "./types";

/* TikTok: Login Kit (OAuth 2.0) und Content Posting API (Direct Post). Env TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET.
 * Alle Endpunkte: TODO verify against current docs (developers.tiktok.com, CON-007). Unaudited Apps posten nur privat
 * (SELF_ONLY), bis die App den Audit bestanden hat. */

const AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"; // TODO verify against current docs
const TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"; // TODO verify against current docs
const USER_URL = "https://open.tiktokapis.com/v2/user/info/?fields=open_id,display_name,username"; // TODO verify against current docs
const INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"; // TODO verify against current docs
const STATUS_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"; // TODO verify against current docs
const QUERY_URL = "https://open.tiktokapis.com/v2/video/query/?fields=id,like_count,comment_count,share_count,view_count"; // TODO verify against current docs
const SCOPES = "user.info.basic,video.publish,video.upload,video.list"; // TODO verify against current docs
const CHUNK = 10 * 1024 * 1024;

function env() {
  return { key: process.env.TIKTOK_CLIENT_KEY?.trim() ?? "", secret: process.env.TIKTOK_CLIENT_SECRET?.trim() ?? "" };
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  open_id?: string;
  scope?: string;
  error?: string;
  error_description?: string;
}

export const tiktokProvider: Provider = {
  platform: "tiktok",
  label: "TikTok",
  configured: () => Boolean(env().key && env().secret),
  capabilities: () => ({ ...DEFAULT_CAPABILITIES.tiktok }),

  authorizeUrl(state, redirectUri) {
    const { key } = env();
    if (!key) throw new NotConfiguredError("TikTok");
    const q = new URLSearchParams({ client_key: key, scope: SCOPES, response_type: "code", redirect_uri: redirectUri, state });
    return `${AUTH_URL}?${q.toString()}`;
  },

  async exchangeCode(code, redirectUri) {
    const { key, secret } = env();
    if (!key || !secret) throw new NotConfiguredError("TikTok");
    const tok = await postForm<TokenResponse>(TOKEN_URL, { client_key: key, client_secret: secret, code, grant_type: "authorization_code", redirect_uri: redirectUri }, {}, "TikTok Token");
    if (!tok.access_token) throw new ProviderError(`TikTok Token: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    const creds: Credentials = {
      access_token: tok.access_token,
      refresh_token: tok.refresh_token,
      expires_at: expiresAtFrom(tok.expires_in),
      open_id: tok.open_id,
      scope: tok.scope,
    };
    let label = "TikTok-Konto";
    try {
      const user = await getJson<{ data?: { user?: { display_name?: string; username?: string } } }>(USER_URL, bearer(creds.access_token), "TikTok Nutzer");
      label = user.data?.user?.username ? `@${user.data.user.username}` : (user.data?.user?.display_name ?? label);
    } catch {
      /* Label bleibt generisch, Verbindung ist trotzdem gültig */
    }
    return { credentials: creds, account_label: label, external_account_id: tok.open_id ?? null, expires_at: creds.expires_at ?? null };
  },

  async refresh(creds) {
    const { key, secret } = env();
    if (!key || !secret) throw new NotConfiguredError("TikTok");
    if (!creds.refresh_token) throw new ProviderError("TikTok: kein refresh_token vorhanden, bitte neu verbinden.");
    const tok = await postForm<TokenResponse>(TOKEN_URL, { client_key: key, client_secret: secret, grant_type: "refresh_token", refresh_token: creds.refresh_token }, {}, "TikTok Refresh");
    if (!tok.access_token) throw new ProviderError(`TikTok Refresh: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    return { ...creds, access_token: tok.access_token, refresh_token: tok.refresh_token ?? creds.refresh_token, expires_at: expiresAtFrom(tok.expires_in) };
  },

  async publish(creds, input): Promise<PublishResult> {
    const headers = { ...bearer(creds.access_token), "Content-Type": "application/json; charset=UTF-8" };
    const title = (input.title || input.caption).slice(0, 2200); // TODO verify against current docs (Titel-Limit)
    const postInfo = { title, privacy_level: process.env.TIKTOK_PRIVACY_LEVEL ?? "SELF_ONLY", disable_duet: false, disable_comment: false, disable_stitch: false }; // TODO verify against current docs
    let publishId: string | null = null;
    if (input.video_url && (process.env.TIKTOK_PULL_FROM_URL ?? "false") === "true") {
      /* PULL_FROM_URL verlangt eine verifizierte Domain in der TikTok-App */
      const { data } = await postJson<{ data?: { publish_id?: string }; error?: { code?: string; message?: string } }>(
        INIT_URL,
        { post_info: postInfo, source_info: { source: "PULL_FROM_URL", video_url: input.video_url } },
        headers,
        "TikTok Init",
      );
      if (data.error?.code && data.error.code !== "ok") return { status: "failed", external_id: null, external_url: null, error: `TikTok: ${data.error.message ?? data.error.code}` };
      publishId = data.data?.publish_id ?? null;
    } else {
      const bytes = await input.loadVideo();
      if (!bytes) return { status: "failed", external_id: null, external_url: null, error: "Videodatei nicht im Objektspeicher gefunden." };
      const total = Math.max(1, Math.ceil(bytes.length / CHUNK));
      const { data } = await postJson<{ data?: { publish_id?: string; upload_url?: string }; error?: { code?: string; message?: string } }>(
        INIT_URL,
        { post_info: postInfo, source_info: { source: "FILE_UPLOAD", video_size: bytes.length, chunk_size: Math.min(CHUNK, bytes.length), total_chunk_count: total } },
        headers,
        "TikTok Init",
      );
      if (data.error?.code && data.error.code !== "ok") return { status: "failed", external_id: null, external_url: null, error: `TikTok: ${data.error.message ?? data.error.code}` };
      publishId = data.data?.publish_id ?? null;
      const uploadUrl = data.data?.upload_url;
      if (!uploadUrl) return { status: "failed", external_id: null, external_url: null, error: "TikTok lieferte keine Upload-URL." };
      for (let i = 0; i < total; i += 1) {
        const start = i * CHUNK;
        const end = Math.min(bytes.length, start + CHUNK);
        await putBytes(uploadUrl, bytes.subarray(start, end), { "Content-Type": "video/mp4", "Content-Length": String(end - start), "Content-Range": `bytes ${start}-${end - 1}/${bytes.length}` }, "TikTok Upload"); // TODO verify against current docs
      }
    }
    if (!publishId) return { status: "failed", external_id: null, external_url: null, error: "TikTok lieferte keine publish_id." };
    /* Status abfragen (bis 2 Minuten); PUBLISH_COMPLETE liefert die Post-ID */
    for (let i = 0; i < 12; i += 1) {
      await sleep(10_000);
      const { data } = await postJson<{ data?: { status?: string; publicaly_available_post_id?: (string | number)[]; fail_reason?: string } }>(STATUS_URL, { publish_id: publishId }, headers, "TikTok Status"); // TODO verify against current docs
      const st = data.data?.status;
      if (st === "PUBLISH_COMPLETE") {
        const postId = data.data?.publicaly_available_post_id?.[0];
        const id = postId != null ? String(postId) : publishId;
        return { status: "published", external_id: id, external_url: postId != null ? `https://www.tiktok.com/@/video/${id}` : null, error: null };
      }
      if (st === "FAILED") return { status: "failed", external_id: publishId, external_url: null, error: `TikTok: ${data.data?.fail_reason ?? "Veröffentlichung fehlgeschlagen"}` };
    }
    /* Verarbeitung läuft noch: als veröffentlicht mit publish_id melden, Metrik-Abruf löst die Video-ID später auf */
    return { status: "published", external_id: publishId, external_url: null, error: null };
  },

  async fetchMetrics(creds, externalId) {
    const { data } = await postJson<{ data?: { videos?: { id: string; like_count?: number; comment_count?: number; share_count?: number; view_count?: number }[] } }>(
      QUERY_URL,
      { filters: { video_ids: [externalId] } },
      { ...bearer(creds.access_token), "Content-Type": "application/json" },
      "TikTok Video Query",
    ); // TODO verify against current docs (Scope video.list)
    const v = data.data?.videos?.[0];
    if (!v) return {};
    return { views: v.view_count ?? null, likes: v.like_count ?? null, comments: v.comment_count ?? null, shares: v.share_count ?? null };
  },
};
