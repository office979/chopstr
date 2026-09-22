import { DEFAULT_CAPABILITIES } from "@/lib/publishing/capabilities";
import type { Credentials } from "@/lib/repo/types-publishing";
import { bearer, expiresAtFrom, getJson, postForm, sleep } from "./http";
import { NotConfiguredError, ProviderError, type Provider, type PublishResult } from "./types";

/* Instagram Reels über die Graph API (Business- oder Creator-Konto, verknüpft mit einer Facebook-Seite).
 * Env META_APP_ID / META_APP_SECRET. Alle Endpunkte: TODO verify against current docs (developers.facebook.com, CON-007).
 * Der Container-Flow verlangt eine öffentlich erreichbare video_url (NEXT_PUBLIC_MEDIA_BASE_URL). */

const VERSION = process.env.META_GRAPH_VERSION ?? "v21.0"; // TODO verify against current docs
const GRAPH = `https://graph.facebook.com/${VERSION}`;
const AUTH_URL = `https://www.facebook.com/${VERSION}/dialog/oauth`; // TODO verify against current docs
const SCOPES = "instagram_basic,instagram_content_publish,instagram_manage_insights,pages_show_list,pages_read_engagement,business_management"; // TODO verify against current docs

function env() {
  return { id: process.env.META_APP_ID?.trim() ?? "", secret: process.env.META_APP_SECRET?.trim() ?? "" };
}

interface Token {
  access_token?: string;
  expires_in?: number;
  error?: { message?: string };
}

async function longLived(shortToken: string): Promise<Token> {
  const { id, secret } = env();
  const q = new URLSearchParams({ grant_type: "fb_exchange_token", client_id: id, client_secret: secret, fb_exchange_token: shortToken });
  return getJson<Token>(`${GRAPH}/oauth/access_token?${q.toString()}`, {}, "Meta Long-Lived Token"); // TODO verify against current docs
}

export const instagramProvider: Provider = {
  platform: "instagram",
  label: "Instagram",
  configured: () => Boolean(env().id && env().secret),
  capabilities: () => ({ ...DEFAULT_CAPABILITIES.instagram }),

  authorizeUrl(state, redirectUri) {
    const { id } = env();
    if (!id) throw new NotConfiguredError("Instagram");
    const q = new URLSearchParams({ client_id: id, redirect_uri: redirectUri, state, scope: SCOPES, response_type: "code" });
    return `${AUTH_URL}?${q.toString()}`;
  },

  async exchangeCode(code, redirectUri) {
    const { id, secret } = env();
    if (!id || !secret) throw new NotConfiguredError("Instagram");
    const q = new URLSearchParams({ client_id: id, client_secret: secret, redirect_uri: redirectUri, code });
    const short = await getJson<Token>(`${GRAPH}/oauth/access_token?${q.toString()}`, {}, "Meta Token"); // TODO verify against current docs
    if (!short.access_token) throw new ProviderError(`Meta Token: ${short.error?.message ?? "kein access_token"}`);
    const long = await longLived(short.access_token);
    const token = long.access_token ?? short.access_token;
    const expires = expiresAtFrom(long.expires_in ?? short.expires_in ?? 60 * 24 * 3600);
    /* Instagram-Konto über die verknüpfte Seite */
    const pages = await getJson<{ data?: { id: string; name?: string; instagram_business_account?: { id: string; username?: string } }[] }>(
      `${GRAPH}/me/accounts?fields=id,name,instagram_business_account{id,username}`,
      bearer(token),
      "Meta Seiten",
    ); // TODO verify against current docs
    const page = pages.data?.find((p) => p.instagram_business_account?.id);
    if (!page?.instagram_business_account) throw new ProviderError("Kein Instagram-Business-Konto an einer Facebook-Seite gefunden.");
    const creds: Credentials = { access_token: token, expires_at: expires, ig_user_id: page.instagram_business_account.id, page_id: page.id };
    return {
      credentials: creds,
      account_label: page.instagram_business_account.username ? `@${page.instagram_business_account.username}` : (page.name ?? "Instagram-Konto"),
      external_account_id: page.instagram_business_account.id,
      expires_at: expires,
    };
  },

  async refresh(creds) {
    if (!creds.access_token) throw new ProviderError("Instagram: kein Token, bitte neu verbinden.");
    const long = await longLived(creds.access_token);
    if (!long.access_token) throw new ProviderError(`Instagram Refresh: ${long.error?.message ?? "kein access_token"}`);
    return { ...creds, access_token: long.access_token, expires_at: expiresAtFrom(long.expires_in ?? 60 * 24 * 3600) };
  },

  async publish(creds, input): Promise<PublishResult> {
    if (!creds.ig_user_id) return { status: "failed", external_id: null, external_url: null, error: "Verbindung ohne Instagram-Konto." };
    if (!input.video_url) return { status: "failed", external_id: null, external_url: null, error: "Instagram braucht eine öffentliche Video-URL (NEXT_PUBLIC_MEDIA_BASE_URL fehlt)." };
    const token = creds.access_token ?? "";
    const container = await postForm<{ id?: string; error?: { message?: string } }>(
      `${GRAPH}/${creds.ig_user_id}/media`,
      { media_type: "REELS", video_url: input.video_url, caption: input.caption.slice(0, 2200), share_to_feed: "true", access_token: token },
      {},
      "Instagram Container",
    ); // TODO verify against current docs
    if (!container.id) return { status: "failed", external_id: null, external_url: null, error: `Instagram: ${container.error?.message ?? "kein Container"}` };
    /* Container-Status pollen (bis 5 Minuten) */
    for (let i = 0; i < 30; i += 1) {
      await sleep(10_000);
      const st = await getJson<{ status_code?: string; status?: string }>(`${GRAPH}/${container.id}?fields=status_code,status&access_token=${encodeURIComponent(token)}`, {}, "Instagram Container-Status"); // TODO verify against current docs
      if (st.status_code === "FINISHED") break;
      if (st.status_code === "ERROR" || st.status_code === "EXPIRED") return { status: "failed", external_id: container.id, external_url: null, error: `Instagram: Container ${st.status_code} (${st.status ?? "ohne Details"})` };
    }
    const pub = await postForm<{ id?: string; error?: { message?: string } }>(`${GRAPH}/${creds.ig_user_id}/media_publish`, { creation_id: container.id, access_token: token }, {}, "Instagram Publish"); // TODO verify against current docs
    if (!pub.id) return { status: "failed", external_id: container.id, external_url: null, error: `Instagram: ${pub.error?.message ?? "media_publish ohne ID"}` };
    let url: string | null = null;
    try {
      const media = await getJson<{ permalink?: string }>(`${GRAPH}/${pub.id}?fields=permalink&access_token=${encodeURIComponent(token)}`, {}, "Instagram Permalink"); // TODO verify against current docs
      url = media.permalink ?? null;
    } catch {
      /* Permalink optional */
    }
    return { status: "published", external_id: pub.id, external_url: url, error: null };
  },

  async fetchMetrics(creds, externalId) {
    const token = creds.access_token ?? "";
    const metrics = "views,likes,comments,shares,saved,ig_reels_avg_watch_time"; // TODO verify against current docs (plays wurde durch views ersetzt)
    const res = await getJson<{ data?: { name: string; values?: { value?: number }[]; total_value?: { value?: number } }[] }>(
      `${GRAPH}/${externalId}/insights?metric=${metrics}&access_token=${encodeURIComponent(token)}`,
      {},
      "Instagram Insights",
    );
    const get = (name: string): number | null => {
      const m = res.data?.find((d) => d.name === name);
      const v = m?.total_value?.value ?? m?.values?.[0]?.value;
      return typeof v === "number" ? v : null;
    };
    const avgMs = get("ig_reels_avg_watch_time");
    return { views: get("views"), likes: get("likes"), comments: get("comments"), shares: get("shares"), saves: get("saved"), avg_watch_time_s: avgMs != null ? avgMs / 1000 : null };
  },
};
