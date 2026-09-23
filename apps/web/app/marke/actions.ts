"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import { requireRole } from "@/lib/session";
import { isForbiddenError } from "@/lib/auth/permissions";
import { normalizeHex } from "@/lib/color";
import type {
  Address,
  AsrVariant,
  BrandCI,
  BrandProfileInput,
  CaptionPreset,
  CaptionStyle,
  Country,
  GenderMode,
  Platform,
} from "@/lib/repo/types";
import type { CaptionStyleExt, CaptionTextField } from "@/lib/repo/types-api";

export interface BrandFormState {
  ok: boolean;
  message: string;
  errors: Record<string, string>;
}

const ADDRESS: Address[] = ["du", "sie"];
const COUNTRY: Country[] = ["DE", "AT", "CH"];
const GENDER: GenderMode[] = ["neutral", "paarform", "doppelpunkt", "stern", "keine"];
const ASR: AsrVariant[] = ["de", "de-CH"];
const PLATFORM: Platform[] = ["tiktok", "reels", "shorts", "linkedin"];
/* Leere Auswahl im Formular bleibt leer und wird zu NULL: keine ausdrückliche Wahl (Migration 0007) */
const PRESET: CaptionPreset[] = [
  "tiktok_bold",
  "reels_clean",
  "shorts_clean",
  "tiktok_words",
  "reels_words",
  "shorts_words",
  "linkedin_static",
  "corporate_third",
];
const CAPTION_TEXT: CaptionTextField[] = ["text", "text_norm"];

function pick<T extends string>(value: FormDataEntryValue | null, allowed: T[], fallback: T): T {
  const v = typeof value === "string" ? value : "";
  return (allowed as string[]).includes(v) ? (v as T) : fallback;
}

/* Auswahl ohne Vorgabe: leer oder unbekannt wird null, nicht ein leerer Text und nicht ein Ersatzwert */
function optionalPick<T extends string>(value: FormDataEntryValue | null, allowed: T[]): T | null {
  const v = typeof value === "string" ? value.trim() : "";
  return (allowed as string[]).includes(v) ? (v as T) : null;
}

function tags(formData: FormData, name: string, max?: number): string[] {
  const values = formData
    .getAll(name)
    .filter((v): v is string => typeof v === "string")
    .map((v) => v.trim())
    .filter(Boolean);
  const unique = [...new Set(values)];
  return max ? unique.slice(0, max) : unique;
}

/* Hex-Farbe aus dem Formular: leer erlaubt, sonst gültiger Hex-Wert */
function color(formData: FormData, name: string, errors: Record<string, string>): string | undefined {
  const raw = String(formData.get(name) ?? "").trim();
  if (!raw) return undefined;
  const hex = normalizeHex(raw);
  if (!hex) {
    errors[name] = "Bitte einen Hex-Wert wie #020cf5 angeben.";
    return undefined;
  }
  return hex;
}

function flag(formData: FormData, name: string): boolean {
  return formData.get(name) === "true";
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/* Asset-Auswahl aus dem CI-Manager: UUID oder null */
function assetId(formData: FormData, name: string): string | null {
  const raw = String(formData.get(name) ?? "").trim();
  return UUID_RE.test(raw) ? raw : null;
}

export async function saveBrandProfileAction(_prev: BrandFormState, formData: FormData): Promise<BrandFormState> {
  try {
    await requireRole("brand.edit");
  } catch (error) {
    if (isForbiddenError(error)) return { ok: false, message: error.message, errors: {} };
    throw error;
  }
  const errors: Record<string, string> = {};
  const name = String(formData.get("name") ?? "").trim();
  if (name.length < 2) errors.name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";

  const toneAdjectives = tags(formData, "tone_adjectives");
  if (toneAdjectives.length > 3) errors.tone_adjectives = "Höchstens drei Ton-Adjektive.";

  const hookOverlay = Object.fromEntries(PLATFORM.map((p) => [p, flag(formData, `hook_overlay_${p}`)])) as CaptionStyle["hook_overlay"];
  const logoAssetId = assetId(formData, "ci_logo");
  const ci: BrandCI = {
    colors: {
      primary: color(formData, "ci_primary", errors),
      secondary: color(formData, "ci_secondary", errors),
      accent: color(formData, "ci_accent", errors),
    },
    /* CI-Manager (Block B): Verweise auf brand_assets.id, der Worker liest primary_asset_id, logo_asset_id, watermark.enabled */
    fonts: { primary_asset_id: assetId(formData, "ci_primary_font"), secondary_asset_id: assetId(formData, "ci_secondary_font"), fallback: "Inter" },
    logo_asset_id: logoAssetId,
    watermark: { enabled: Boolean(logoAssetId) && flag(formData, "ci_watermark_enabled") },
    lower_third: {
      enabled: flag(formData, "lower_third_enabled"),
      name: String(formData.get("lower_third_name") ?? "").trim().slice(0, 80),
      role: String(formData.get("lower_third_role") ?? "").trim().slice(0, 80),
      position: "bottom_left",
    },
    hook_overlay: hookOverlay,
  };
  const captionStyle: CaptionStyleExt = {
    highlight_color: color(formData, "caption_highlight", errors),
    hook_overlay: hookOverlay,
    /* 5c: Captions aus Original (text) oder Standardform (text_norm, Schweizerdeutsch-Beta) */
    caption_text_field: pick(formData.get("caption_text_field"), CAPTION_TEXT, "text"),
  };

  if (Object.keys(errors).length > 0) {
    return { ok: false, message: "Bitte die markierten Felder prüfen.", errors };
  }

  const idRaw = String(formData.get("id") ?? "");
  const input: BrandProfileInput = {
    id: idRaw || undefined,
    name,
    address: pick(formData.get("address"), ADDRESS, "du"),
    country: pick(formData.get("country"), COUNTRY, "AT"),
    gender_mode: pick(formData.get("gender_mode"), GENDER, "neutral"),
    asr_variant: pick(formData.get("asr_variant"), ASR, "de"),
    default_platform: pick(formData.get("default_platform"), PLATFORM, "linkedin"),
    caption_preset: optionalPick(formData.get("caption_preset"), PRESET),
    tone_adjectives: toneAdjectives.slice(0, 3),
    brand_vocab: tags(formData, "brand_vocab"),
    protected_terms: tags(formData, "protected_terms"),
    banned_phrases: tags(formData, "banned_phrases"),
    ci,
    caption_style: captionStyle,
  };

  const repo = getRepo();
  /* Nur Assets dieses Profils dürfen referenziert werden */
  if (input.id) {
    const assets = await repo.listBrandAssets(input.id);
    const ids = new Set(assets.map((a) => a.id));
    const fonts = ci.fonts ?? {};
    if (fonts.primary_asset_id && !ids.has(fonts.primary_asset_id)) fonts.primary_asset_id = null;
    if (fonts.secondary_asset_id && !ids.has(fonts.secondary_asset_id)) fonts.secondary_asset_id = null;
    if (ci.logo_asset_id && !ids.has(ci.logo_asset_id)) {
      ci.logo_asset_id = null;
      ci.watermark = { enabled: false };
    }
  }
  const saved = await repo.saveBrandProfile(input);
  await repo.audit({
    action: "brand_profile.saved",
    entity: "brand_profiles",
    entity_id: saved.id,
    payload: { version: saved.version, fonts: ci.fonts, logo_asset_id: ci.logo_asset_id, watermark: ci.watermark?.enabled ?? false },
  });
  revalidatePath("/marke");
  revalidatePath("/upload");
  return { ok: true, message: `Aussehen gespeichert (Version ${saved.version}).`, errors: {} };
}
