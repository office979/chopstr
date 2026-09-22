import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { signUploadToken, UPLOAD_TOKEN_TTL_S } from "@/lib/auth/upload-token";
import { getQuota } from "@/lib/billing/quota";

export const dynamic = "force-dynamic";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/* POST: Upload-Token für tusd (Rolle editor oder höher). Prüft das Stundenkontingent (402 bei Ausschöpfung ohne
 * Mehrverbrauch). Body: { brand_profile_id?: string }. Antwort: { upload_token, expires_in_s, quota }. */
export async function POST(request: NextRequest) {
  const auth = await requireApiRole("source.upload");
  if (auth instanceof Response) return auth;

  let body: { brand_profile_id?: unknown } = {};
  try {
    const text = await request.text();
    body = text ? (JSON.parse(text) as typeof body) : {};
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const repo = getRepo();
  let brandProfileId: string | null = null;
  if (typeof body.brand_profile_id === "string" && body.brand_profile_id) {
    if (!UUID_RE.test(body.brand_profile_id)) return Response.json({ error: "Markenprofil ungültig" }, { status: 400 });
    const brand = await repo.getBrandProfile(body.brand_profile_id);
    if (!brand) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });
    brandProfileId = brand.id;
  }

  const quota = await getQuota(repo);
  if (quota.exhausted) {
    return Response.json(
      { error: quota.message, code: "quota_exhausted", used_minutes: quota.used_minutes, included_minutes: quota.included_minutes },
      { status: 402 },
    );
  }

  let uploadToken: string;
  try {
    uploadToken = signUploadToken({ workspace_id: auth.workspaceId, user_id: auth.userId, brand_profile_id: brandProfileId });
  } catch (error) {
    /* Produktion ohne TUS_HOOK_SECRET: sauber melden statt 500-Stacktrace */
    return Response.json({ error: error instanceof Error ? error.message : "Upload-Token konnte nicht erzeugt werden" }, { status: 500 });
  }
  await repo.audit({
    action: "upload.token_issued",
    entity: "workspaces",
    entity_id: auth.workspaceId,
    payload: { brand_profile_id: brandProfileId, used_minutes: quota.used_minutes, included_minutes: quota.included_minutes },
  });
  return Response.json({
    upload_token: uploadToken,
    expires_in_s: UPLOAD_TOKEN_TTL_S,
    quota: { used_minutes: quota.used_minutes, included_minutes: quota.included_minutes, allow_overage: quota.allow_overage },
  });
}
