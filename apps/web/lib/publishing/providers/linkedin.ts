import { DEFAULT_CAPABILITIES } from "@/lib/publishing/capabilities";
import type { Credentials } from "@/lib/repo/types-publishing";
import { bearer, expiresAtFrom, getJson, postForm, postJson, putBytes } from "./http";
import { NotConfiguredError, ProviderError, type Provider, type PublishResult } from "./types";

/* LinkedIn Community Management API (Videos API + Posts API, versioniert). Env LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET.
 * Postet als Mitglied (urn:li:person:…) über OpenID Connect + w_member_social. Alle Endpunkte:
 * TODO verify against current docs (learn.microsoft.com/linkedin, CON-007). */

const AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"; // TODO verify against current docs
const TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"; // TODO verify against current docs
const USERINFO_URL = "https://api.linkedin.com/v2/userinfo"; // TODO verify against current docs
const REST = "https://api.linkedin.com/rest";
const VERSION = process.env.LINKEDIN_VERSION ?? "202409"; // TODO verify against current docs (monatliche Versionen)
const SCOPES = "openid profile w_member_social r_member_postAnalytics"; // TODO verify against current docs (r_member_postAnalytics ist Partner-Zugang)

function env() {
  return { id: process.env.LINKEDIN_CLIENT_ID?.trim() ?? "", secret: process.env.LINKEDIN_CLIENT_SECRET?.trim() ?? "" };
}

function restHeaders(token: string | undefined): Record<string, string> {
  return { ...bearer(token), "LinkedIn-Version": VERSION, "X-Restli-Protocol-Version": "2.0.0" };
}

interface Token {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  scope?: string;
  error?: string;
  error_description?: string;
}

export const linkedinProvider: Provider = {
  platform: "linkedin",
  label: "LinkedIn",
  configured: () => Boolean(env().id && env().secret),
  capabilities: () => ({ ...DEFAULT_CAPABILITIES.linkedin }),

  authorizeUrl(state, redirectUri) {
    const { id } = env();
    if (!id) throw new NotConfiguredError("LinkedIn");
    const q = new URLSearchParams({ response_type: "code", client_id: id, redirect_uri: redirectUri, state, scope: SCOPES });
    return `${AUTH_URL}?${q.toString()}`;
  },

  async exchangeCode(code, redirectUri) {
    const { id, secret } = env();
    if (!id || !secret) throw new NotConfiguredError("LinkedIn");
    const tok = await postForm<Token>(TOKEN_URL, { grant_type: "authorization_code", code, client_id: id, client_secret: secret, redirect_uri: redirectUri }, {}, "LinkedIn Token");
    if (!tok.access_token) throw new ProviderError(`LinkedIn Token: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    const me = await getJson<{ sub?: string; name?: string }>(USERINFO_URL, bearer(tok.access_token), "LinkedIn Userinfo"); // TODO verify against current docs
    if (!me.sub) throw new ProviderError("LinkedIn lieferte keine Mitglieds-ID (sub).");
    const urn = `urn:li:person:${me.sub}`;
    const creds: Credentials = { access_token: tok.access_token, refresh_token: tok.refresh_token, expires_at: expiresAtFrom(tok.expires_in), scope: tok.scope, person_urn: urn };
    return { credentials: creds, account_label: me.name ?? "LinkedIn-Profil", external_account_id: urn, expires_at: creds.expires_at ?? null };
  },

  async refresh(creds) {
    const { id, secret } = env();
    if (!id || !secret) throw new NotConfiguredError("LinkedIn");
    if (!creds.refresh_token) throw new ProviderError("LinkedIn: kein refresh_token (programmatischer Refresh braucht Freischaltung), bitte neu verbinden.");
    const tok = await postForm<Token>(TOKEN_URL, { grant_type: "refresh_token", refresh_token: creds.refresh_token, client_id: id, client_secret: secret }, {}, "LinkedIn Refresh"); // TODO verify against current docs
    if (!tok.access_token) throw new ProviderError(`LinkedIn Refresh: ${tok.error_description ?? tok.error ?? "kein access_token"}`);
    return { ...creds, access_token: tok.access_token, refresh_token: tok.refresh_token ?? creds.refresh_token, expires_at: expiresAtFrom(tok.expires_in) };
  },

  async publish(creds, input): Promise<PublishResult> {
    if (!creds.person_urn) return { status: "failed", external_id: null, external_url: null, error: "Verbindung ohne Mitglieds-URN." };
    const bytes = await input.loadVideo();
    if (!bytes) return { status: "failed", external_id: null, external_url: null, error: "Videodatei nicht im Objektspeicher gefunden." };
    const headers = restHeaders(creds.access_token);
    const init = await postJson<{ value?: { uploadInstructions?: { uploadUrl: string; firstByte: number; lastByte: number }[]; video?: string; uploadToken?: string } }>(
      `${REST}/videos?action=initializeUpload`,
      { initializeUploadRequest: { owner: creds.person_urn, fileSizeBytes: bytes.length, uploadCaptions: false, uploadThumbnail: false } },
      headers,
      "LinkedIn Video Init",
    ); // TODO verify against current docs
    const v = init.data.value;
    if (!v?.video || !v.uploadInstructions?.length) return { status: "failed", external_id: null, external_url: null, error: "LinkedIn lieferte keine Upload-Anweisungen." };
    const etags: string[] = [];
    for (const part of v.uploadInstructions) {
      const res = await putBytes(part.uploadUrl, bytes.subarray(part.firstByte, part.lastByte + 1), { "Content-Type": "application/octet-stream" }, "LinkedIn Video Upload");
      etags.push(res.headers.get("etag") ?? "");
    }
    await postJson(`${REST}/videos?action=finalizeUpload`, { finalizeUploadRequest: { video: v.video, uploadToken: v.uploadToken ?? "", uploadedPartIds: etags } }, headers, "LinkedIn Video Finalize"); // TODO verify against current docs
    const post = await postJson<unknown>(
      `${REST}/posts`,
      {
        author: creds.person_urn,
        commentary: input.caption.slice(0, 3000),
        visibility: "PUBLIC",
        distribution: { feedDistribution: "MAIN_FEED", targetEntities: [], thirdPartyDistributionChannels: [] },
        content: { media: { title: input.title.slice(0, 200) || "Video", id: v.video } },
        lifecycleState: "PUBLISHED",
        isReshareDisabledByAuthor: false,
      },
      headers,
      "LinkedIn Post",
    ); // TODO verify against current docs
    const postUrn = post.headers.get("x-restli-id") ?? post.headers.get("x-linkedin-id");
    if (!postUrn) return { status: "failed", external_id: v.video, external_url: null, error: "LinkedIn lieferte keine Post-URN." };
    return { status: "published", external_id: postUrn, external_url: `https://www.linkedin.com/feed/update/${encodeURIComponent(postUrn)}`, error: null };
  },

  async fetchMetrics(creds, externalId) {
    const headers = restHeaders(creds.access_token);
    const social = await getJson<{ likesSummary?: { totalLikes?: number }; commentsSummary?: { totalFirstLevelComments?: number; aggregatedTotalComments?: number } }>(
      `${REST}/socialActions/${encodeURIComponent(externalId)}`,
      headers,
      "LinkedIn Social Actions",
    ); // TODO verify against current docs
    const out: Record<string, number | null> = {
      likes: social.likesSummary?.totalLikes ?? null,
      comments: social.commentsSummary?.aggregatedTotalComments ?? social.commentsSummary?.totalFirstLevelComments ?? null,
    };
    try {
      /* Impressionen und Reshares je Post (Member Post Analytics, Partner-Zugang) */
      const q = new URLSearchParams({ q: "entity", entity: `(share:${externalId})`, queryType: "IMPRESSION" });
      const a = await getJson<{ elements?: { count?: number }[] }>(`${REST}/memberCreatorPostAnalytics?${q.toString()}`, headers, "LinkedIn Post Analytics"); // TODO verify against current docs
      out.views = a.elements?.[0]?.count ?? null;
      const r = new URLSearchParams({ q: "entity", entity: `(share:${externalId})`, queryType: "RESHARE" });
      const b = await getJson<{ elements?: { count?: number }[] }>(`${REST}/memberCreatorPostAnalytics?${r.toString()}`, headers, "LinkedIn Post Analytics"); // TODO verify against current docs
      out.shares = b.elements?.[0]?.count ?? null;
    } catch {
      /* ohne Partner-Zugang bleiben Impressionen und Reshares null (Capability conditional) */
    }
    return out;
  },
};
