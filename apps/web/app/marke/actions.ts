"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
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
const PRESET: CaptionPreset[] = ["tiktok_bold", "reels_clean", "shorts_clean", "linkedin_static", "corporate_third"];

function pick<T extends string>(value: FormDataEntryValue | null, allowed: T[], fallback: T): T {
  const v = typeof value === "string" ? value : "";
  return (allowed as string[]).includes(v) ? (v as T) : fallback;
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

export async function saveBrandProfileAction(_prev: BrandFormState, formData: FormData): Promise<BrandFormState> {
  const errors: Record<string, string> = {};
  const name = String(formData.get("name") ?? "").trim();
  if (name.length < 2) errors.name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";

  const toneAdjectives = tags(formData, "tone_adjectives");
  if (toneAdjectives.length > 3) errors.tone_adjectives = "Höchstens drei Ton-Adjektive.";

  const ci: BrandCI = {
    colors: {
      primary: color(formData, "ci_primary", errors),
      secondary: color(formData, "ci_secondary", errors),
      accent: color(formData, "ci_accent", errors),
    },
    fonts: { primary_key: null, secondary_key: null },
    logo_key: null,
    lower_third: {
      enabled: flag(formData, "lower_third_enabled"),
      name: String(formData.get("lower_third_name") ?? "").trim().slice(0, 80),
      role: String(formData.get("lower_third_role") ?? "").trim().slice(0, 80),
    },
  };
  const captionStyle: CaptionStyle = {
    highlight_color: color(formData, "caption_highlight", errors),
    hook_overlay: Object.fromEntries(PLATFORM.map((p) => [p, flag(formData, `hook_overlay_${p}`)])) as CaptionStyle["hook_overlay"],
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
    caption_preset: pick(formData.get("caption_preset"), PRESET, "linkedin_static"),
    tone_adjectives: toneAdjectives.slice(0, 3),
    brand_vocab: tags(formData, "brand_vocab"),
    protected_terms: tags(formData, "protected_terms"),
    banned_phrases: tags(formData, "banned_phrases"),
    ci,
    caption_style: captionStyle,
  };

  const repo = getRepo();
  const saved = await repo.saveBrandProfile(input);
  await repo.audit({
    action: "brand_profile.saved",
    entity: "brand_profiles",
    entity_id: saved.id,
    payload: { version: saved.version },
  });
  revalidatePath("/marke");
  revalidatePath("/upload");
  return { ok: true, message: `Markenprofil gespeichert (Version ${saved.version}).`, errors: {} };
}
