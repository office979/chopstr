import type { NextRequest } from "next/server";
import { getRepo } from "@/lib/repo";
import { apiRoute } from "@/lib/api/handler";
import { apiJson } from "@/lib/api/errors";
import { readJsonBody } from "@/lib/api/validate";
import { requestSchema, resolveRef } from "@/lib/api/openapi";
import { serializeBrandProfile } from "@/lib/api/serializers";
import type { BrandProfileInput } from "@/lib/repo/types";

export const dynamic = "force-dynamic";

export const GET = apiRoute("read", async () => {
  const profiles = await getRepo().listBrandProfiles();
  return apiJson({ brand_profiles: profiles.map(serializeBrandProfile) });
});

type Body = Partial<Omit<BrandProfileInput, "id">> & { name: string };

function tags(v: unknown): string[] {
  return Array.isArray(v) ? [...new Set(v.filter((x): x is string => typeof x === "string").map((x) => x.trim()).filter(Boolean))] : [];
}

export const POST = apiRoute("write", async (request: NextRequest, { auth }) => {
  const body = await readJsonBody<Body>(request, requestSchema("CreateBrandProfile"), resolveRef);
  const input: BrandProfileInput = {
    name: body.name.trim(),
    address: body.address ?? "du",
    country: body.country ?? "AT",
    gender_mode: body.gender_mode ?? "neutral",
    asr_variant: body.asr_variant ?? "de",
    default_platform: body.default_platform ?? "linkedin",
    /* Ohne Angabe bleibt es NULL: keine ausdrückliche Wahl, das Format entscheidet (Migration 0007) */
    caption_preset: body.caption_preset ?? null,
    tone_adjectives: tags(body.tone_adjectives).slice(0, 3),
    brand_vocab: tags(body.brand_vocab),
    protected_terms: tags(body.protected_terms),
    banned_phrases: tags(body.banned_phrases),
    ci: body.ci ?? {},
    caption_style: body.caption_style ?? {},
  };
  const repo = getRepo();
  const saved = await repo.saveBrandProfile(input);
  await repo.audit({ action: "brand_profile.saved", entity: "brand_profiles", entity_id: saved.id, payload: { version: saved.version, via: "api", api_key_id: auth.key.id } });
  return apiJson({ brand_profile: serializeBrandProfile(saved) }, 201);
});
