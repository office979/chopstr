"use server";

import { revalidatePath } from "next/cache";
import { getRepo } from "@/lib/repo";
import type {
  Address,
  AsrVariant,
  BrandProfileInput,
  CaptionPreset,
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

export async function saveBrandProfileAction(_prev: BrandFormState, formData: FormData): Promise<BrandFormState> {
  const errors: Record<string, string> = {};
  const name = String(formData.get("name") ?? "").trim();
  if (name.length < 2) errors.name = "Bitte einen Namen mit mindestens zwei Zeichen angeben.";

  const toneAdjectives = tags(formData, "tone_adjectives");
  if (toneAdjectives.length > 3) errors.tone_adjectives = "Höchstens drei Ton-Adjektive.";

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
