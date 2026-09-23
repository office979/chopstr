import type { BrandProfile, BrandProfileVersion } from "@/lib/repo/types";

/* Historie des Markenprofils: je Snapshot die Felder, die sich zum nächsten Stand (oder zum aktuellen Profil) geändert haben */

const FIELD_LABELS: Record<string, string> = {
  name: "Name",
  address: "Anrede",
  country: "Land",
  gender_mode: "Gender-Modus",
  asr_variant: "ASR-Variante",
  brand_vocab: "Wörterbuch",
  protected_terms: "Geschützte Begriffe",
  banned_phrases: "Gesperrte Phrasen",
  tone_adjectives: "Ton-Adjektive",
  default_platform: "Plattform",
  caption_preset: "Untertitel-Stil",
  "ci.colors": "Farben",
  "ci.fonts": "Fonts",
  "ci.logo_asset_id": "Logo",
  "ci.watermark": "Wasserzeichen",
  "ci.lower_third": "Bauchbinde",
  "ci.hook_overlay": "Hook-Overlay",
  "caption_style.highlight_color": "Caption-Highlight",
  "caption_style.hook_overlay": "Hook-Overlay",
};

export interface HistoryEntry {
  id: string;
  version: number;
  snapshot_version: number;
  changed_at: string;
  changed_by_label: string | null;
  changed_fields: string[];
}

/* Leere Werte (null, "", false, leere Objekte) zählen als „nicht gesetzt“, damit ein erstes Speichern nicht alles als geändert meldet */
function norm(v: unknown): string {
  if (v == null || v === "" || v === false) return "";
  if (Array.isArray(v)) return JSON.stringify([...v].map((x) => String(x)).sort());
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    const entries = Object.keys(o)
      .sort()
      .map((k) => [k, norm(o[k])] as const)
      .filter(([, val]) => val !== "");
    return entries.length ? JSON.stringify(Object.fromEntries(entries)) : "";
  }
  return JSON.stringify(v);
}

export function changedFields(before: BrandProfile, after: BrandProfile): string[] {
  const out: string[] = [];
  for (const key of ["name", "address", "country", "gender_mode", "asr_variant", "brand_vocab", "protected_terms", "banned_phrases", "tone_adjectives", "default_platform", "caption_preset"] as const) {
    if (norm(before[key]) !== norm(after[key])) out.push(FIELD_LABELS[key]);
  }
  const ciKeys = new Set([...Object.keys(before.ci ?? {}), ...Object.keys(after.ci ?? {})]);
  for (const k of ciKeys) {
    const b = (before.ci as Record<string, unknown>)?.[k];
    const a = (after.ci as Record<string, unknown>)?.[k];
    if (norm(b) !== norm(a)) out.push(FIELD_LABELS[`ci.${k}`] ?? `CI ${k}`);
  }
  const csKeys = new Set([...Object.keys(before.caption_style ?? {}), ...Object.keys(after.caption_style ?? {})]);
  for (const k of csKeys) {
    const b = (before.caption_style as Record<string, unknown>)?.[k];
    const a = (after.caption_style as Record<string, unknown>)?.[k];
    if (norm(b) !== norm(a)) {
      const label = FIELD_LABELS[`caption_style.${k}`] ?? `Caption ${k}`;
      if (!out.includes(label)) out.push(label);
    }
  }
  return out;
}

/* versions: neueste zuerst; der jüngste Snapshot wird mit dem aktuellen Profil verglichen */
export function buildHistory(versions: BrandProfileVersion[], current: BrandProfile): HistoryEntry[] {
  return versions.map((v, i) => {
    const next = i === 0 ? current : versions[i - 1].snapshot;
    return {
      id: v.id,
      version: v.version,
      snapshot_version: v.snapshot.version,
      changed_at: v.changed_at,
      changed_by_label: v.changed_by_label ?? null,
      changed_fields: changedFields(v.snapshot, next),
    };
  });
}
