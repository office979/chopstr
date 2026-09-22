import { createHash } from "node:crypto";
import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { requireApiRole } from "@/lib/auth/guard";
import { getStore } from "@/lib/storage";
import { LICENSE_TEXT, extensionOf, isAssetKind, mimeFor, validateAssetFile } from "@/lib/brand/assets";
import { readFontMeta } from "@/lib/brand/fonts";
import type { BrandCI, BrandProfileInput } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ id: string }> };

/* POST multipart (file, kind, license=true): CI-Asset hochladen (PHASE4.md, Abschnitt 8) → derived-Bucket unter
 * brand/<profile>/<kind>/<sha>.<ext>, Zeile in brand_assets, Audit brand.asset_uploaded mit Lizenztext. */
export async function POST(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("brand.assets");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  const repo = getRepo();
  const profile = await repo.getBrandProfile(id);
  if (!profile) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return Response.json({ error: "Erwartet multipart/form-data" }, { status: 400 });
  }
  const kind = form.get("kind");
  const file = form.get("file");
  const license = form.get("license");
  if (!isAssetKind(kind)) return Response.json({ error: "kind muss font, logo, lower_third_bg oder watermark sein" }, { status: 400 });
  if (!(file instanceof File)) return Response.json({ error: "Bitte eine Datei wählen." }, { status: 400 });
  if (license !== "true" && license !== "on") return Response.json({ error: "Bitte die Lizenz bestätigen.", field: "license" }, { status: 400 });
  const problem = validateAssetFile(kind, file.name, file.size);
  if (problem) return Response.json({ error: problem, field: "file" }, { status: 400 });

  const bytes = new Uint8Array(await file.arrayBuffer());
  const ext = extensionOf(file.name);
  const sha = createHash("sha256").update(bytes).digest("hex");
  const key = `brand/${profile.id}/${kind}/${sha}.${ext}`;
  const mime = mimeFor(ext);
  const font = kind === "font" ? await readFontMeta(bytes, file.name) : null;

  const store = getStore();
  await store.put("derived", key, bytes, mime);
  const asset = await repo.createBrandAsset({
    brand_profile_id: profile.id,
    kind,
    name: file.name.slice(0, 160),
    storage_key: key,
    mime_type: mime,
    size_bytes: bytes.byteLength,
    sha256: sha,
    font_family: font?.family ?? null,
    font_weight: font?.weight ?? null,
    license_note: LICENSE_TEXT,
  });
  await repo.audit({
    action: "brand.asset_uploaded",
    entity: "brand_assets",
    entity_id: asset.id,
    payload: {
      brand_profile_id: profile.id,
      kind,
      name: asset.name,
      size_bytes: asset.size_bytes,
      sha256: sha,
      storage_key: key,
      font_family: asset.font_family,
      font_weight: asset.font_weight,
      font_parsed: font?.parsed ?? null,
      license_note: LICENSE_TEXT,
      storage: store.kind,
    },
  });
  return Response.json({ ok: true, asset, storage: store.kind }, { status: 201 });
}

/* DELETE { asset_id }: Asset entfernen (Objekt und Zeile). Verweise im CI werden gelöst, mit Snapshot in der Historie. */
export async function DELETE(request: NextRequest, { params }: Params) {
  const auth = await requireApiRole("brand.assets");
  if (auth instanceof Response) return auth;
  const { id } = await params;
  let body: { asset_id?: unknown };
  try {
    body = (await request.json()) as { asset_id?: unknown };
  } catch {
    return Response.json({ error: "Ungültiger JSON-Body" }, { status: 400 });
  }
  const assetId = typeof body.asset_id === "string" ? body.asset_id : "";
  const repo = getRepo();
  const profile = await repo.getBrandProfile(id);
  if (!profile) return Response.json({ error: "Markenprofil nicht gefunden" }, { status: 404 });
  const asset = await repo.getBrandAsset(assetId);
  if (!asset || asset.brand_profile_id !== id) return Response.json({ error: "Asset nicht gefunden" }, { status: 404 });

  const ci: BrandCI = profile.ci ?? {};
  const referenced = ci.fonts?.primary_asset_id === asset.id || ci.fonts?.secondary_asset_id === asset.id || ci.logo_asset_id === asset.id;
  if (referenced) {
    const nextCi: BrandCI = {
      ...ci,
      fonts: {
        ...ci.fonts,
        primary_asset_id: ci.fonts?.primary_asset_id === asset.id ? null : (ci.fonts?.primary_asset_id ?? null),
        secondary_asset_id: ci.fonts?.secondary_asset_id === asset.id ? null : (ci.fonts?.secondary_asset_id ?? null),
      },
      logo_asset_id: ci.logo_asset_id === asset.id ? null : (ci.logo_asset_id ?? null),
    };
    const input: BrandProfileInput = {
      id: profile.id,
      name: profile.name,
      address: profile.address,
      country: profile.country,
      gender_mode: profile.gender_mode,
      asr_variant: profile.asr_variant,
      brand_vocab: profile.brand_vocab,
      protected_terms: profile.protected_terms,
      banned_phrases: profile.banned_phrases,
      tone_adjectives: profile.tone_adjectives,
      default_platform: profile.default_platform,
      caption_preset: profile.caption_preset,
      caption_style: profile.caption_style,
      ci: nextCi,
    };
    await repo.saveBrandProfile(input);
  }
  const removed = await repo.deleteBrandAsset(asset.id);
  if (removed) {
    try {
      await getStore().delete("derived", removed.storage_key);
    } catch (error) {
      console.warn("[brand] Objekt konnte nicht gelöscht werden:", error instanceof Error ? error.message : error);
    }
  }
  await repo.audit({
    action: "brand.asset_deleted",
    entity: "brand_assets",
    entity_id: asset.id,
    payload: { brand_profile_id: id, kind: asset.kind, name: asset.name, storage_key: asset.storage_key, sha256: asset.sha256, references_cleared: referenced },
  });
  return Response.json({ ok: true, references_cleared: referenced });
}
