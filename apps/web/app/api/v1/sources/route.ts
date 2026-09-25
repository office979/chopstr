import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson, badRequest, notFound, paymentRequired } from "@/lib/api/errors";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializeSource } from "@/lib/api/serializers";
import { getQuota } from "@/lib/billing/quota";
import { noteUsageThresholds } from "@/lib/outbox";
import { signUploadToken, UPLOAD_TOKEN_TTL_S } from "@/lib/auth/upload-token";
import type { Brief, RightsStatus, SourceInput } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

/* GET /api/v1/sources?status=&limit= → { sources: [...] } */
export const GET = apiRoute("read", async (request: NextRequest) => {
  const status = request.nextUrl.searchParams.get("status");
  const limitRaw = Number(request.nextUrl.searchParams.get("limit") ?? 100);
  const limit = Number.isFinite(limitRaw) && limitRaw > 0 ? Math.min(500, Math.floor(limitRaw)) : 100;
  let sources = await getRepo().listSources();
  if (status) sources = sources.filter((s) => s.status === status);
  return apiJson({ sources: sources.slice(0, limit).map(serializeSource), total: sources.length });
});

interface CreateSourceBody {
  title: string;
  brand_profile_id?: string | null;
  rights_status?: RightsStatus;
  rights_confirmed: true;
  source_owner?: string | null;
  source_title?: string | null;
  source_url?: string | null;
  expected_speakers?: number | null;
  brief?: Brief & { import_url?: string };
  upload: "tus" | "url";
}

/* POST /api/v1/sources: Quelle anlegen (upload tus oder url), Kontingent-Gate 402, usage.threshold-Merker */
export const POST = apiRoute("write", async (request: NextRequest, { auth }) => {
  const body = await readJsonBody<CreateSourceBody>(request, requestSchema("CreateSource"), resolveRef);
  const repo = getRepo();
  const rightsStatus: RightsStatus = body.rights_status ?? "own";
  const sourceOwner = body.source_owner?.trim() || null;
  const sourceUrl = body.source_url?.trim() || null;
  /* Der Import per Adresse ist noch nicht gebaut, und zwar vollständig nicht.
   *
   * Die Schnittstelle nimmt ``upload: "url"`` an, schreibt die Adresse nach ``brief.import_url``
   * und startet den Ablauf. Danach passiert nichts Gutes: kein Schritt im Worker holt diese Datei
   * je herunter (``activities/ingest.run`` lädt ausschliesslich aus dem Objektspeicher über
   * ``storage_key``), also lief das Projekt in einen Fehler, nachdem die Antwort „201 angelegt"
   * gesagt hatte. Ein Kontingent war da schon verbucht.
   *
   * Bis das Herunterladen wirklich existiert, sagt die Schnittstelle das vorher statt hinterher.
   * Was dafür zuerst entschieden werden muss, steht in docs/RISIKEN-UND-RUECKFRAGEN.md: welche
   * Quellen erlaubt sind (das Herunterladen fremder Videos ist im DACH-Raum nicht schon deshalb
   * zulässig, weil jemand ein Häkchen bei „ich habe die Rechte" setzt) und wie der Abruf gegen
   * Anfragen ins eigene Netz abgesichert wird. */
  if (body.upload === "url") {
    throw badRequest(
      "Der Import per Adresse ist noch nicht verfügbar. Lade die Datei per tus hoch (upload = tus).",
      "url_import_unavailable",
    );
  }
  if (sourceUrl && !/^https?:\/\//i.test(sourceUrl)) throw badRequest("source_url muss mit http(s) beginnen.", "validation_failed");

  let brandProfileId: string | null = null;
  if (body.brand_profile_id) {
    const brand = await repo.getBrandProfile(body.brand_profile_id);
    if (!brand) throw notFound("Markenprofil nicht gefunden.");
    brandProfileId = brand.id;
  } else {
    brandProfileId = (await repo.listBrandProfiles())[0]?.id ?? null;
  }

  const quota = await getQuota(repo);
  void noteUsageThresholds(auth.workspaceId, quota);
  if (quota.exhausted) throw paymentRequired(quota.message ?? "Stundenkontingent ausgeschöpft.", "quota_exhausted");

  const brief: Brief = { ...(body.brief ?? {}) };

  const input: SourceInput = {
    brand_profile_id: brandProfileId,
    title: body.title.trim(),
    original_filename: null,
    mime_type: null,
    size_bytes: null,
    storage_key: "",
    rights_status: rightsStatus,
    rights_confirmed_by: auth.session.userId,
    source_owner: sourceOwner,
    source_title: body.source_title?.trim() || null,
    source_url: sourceUrl,
    expected_speakers: body.expected_speakers ?? null,
    brief,
    status: "uploading",
  };
  const source = await repo.createSource(input);
  await repo.audit({
    action: "source.created",
    entity: "sources",
    entity_id: source.id,
    payload: { via: "api", api_key_id: auth.key.id, upload: body.upload, rights_status: rightsStatus, source_url: sourceUrl },
  });
  await repo.audit({ action: "rights.confirmed", entity: "sources", entity_id: source.id, payload: { rights_status: rightsStatus, confirmed_by: auth.session.userId, via: "api" } });

  /* Es bleibt nur der Weg über tus: der Import per Adresse ist oben abgewiesen. */
  let uploadToken: string;
  try {
    uploadToken = signUploadToken({ workspace_id: auth.workspaceId, user_id: auth.session.userId, brand_profile_id: brandProfileId });
  } catch (error) {
    throw new (await import("@/lib/api/errors")).ApiError(500, "not_configured", error instanceof Error ? error.message : "Upload-Token konnte nicht erzeugt werden.");
  }
  const tusEndpoint = process.env.NEXT_PUBLIC_TUS_ENDPOINT ?? process.env.TUS_ENDPOINT ?? "http://localhost:1080/files/";
  return apiJson(
    {
      source: serializeSource(source),
      upload_token: uploadToken,
      upload_token_expires_in_s: UPLOAD_TOKEN_TTL_S,
      tus_endpoint: tusEndpoint,
      tus_metadata: { upload_token: uploadToken, client_ref: source.id, title: source.title, rights_confirmed: "true", rights_status: rightsStatus },
      workflow_id: null,
      hint: "Datei per tus mit den Metadaten aus tus_metadata hochladen; der Hook ergänzt die Quelle und startet die Pipeline.",
    },
    201,
  );
});
