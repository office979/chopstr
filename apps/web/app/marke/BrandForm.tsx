"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { TagInput } from "@/components/ui/TagInput";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ColorField } from "@/components/ui/ColorField";
import { Toggle } from "@/components/ui/Toggle";
import type { BrandAsset, BrandProfile, Platform } from "@/lib/repo/types";
import type { CaptionStyleExt } from "@/lib/repo/types-api";
import { AssetsCard } from "./AssetsCard";
import { PLATFORMS, PLATFORM_LABELS } from "@/lib/clips/labels";
import { useState } from "react";
import { saveBrandProfileAction, type BrandFormState } from "./actions";

const initialState: BrandFormState = { ok: false, message: "", errors: {} };

export function BrandForm({ profile, assets, canUploadAssets }: { profile: BrandProfile | null; assets: BrandAsset[]; canUploadAssets: boolean }) {
  const [state, action, pending] = useActionState(saveBrandProfileAction, initialState);
  const ci = profile?.ci ?? {};
  const style: CaptionStyleExt = profile?.caption_style ?? {};
  const [lowerThird, setLowerThird] = useState(ci.lower_third?.enabled ?? false);
  const [hookOverlay, setHookOverlay] = useState<Record<Platform, boolean>>({
    tiktok: style.hook_overlay?.tiktok ?? true,
    reels: style.hook_overlay?.reels ?? true,
    shorts: style.hook_overlay?.shorts ?? true,
    linkedin: style.hook_overlay?.linkedin ?? false,
  });

  return (
    <form action={action} className="flex flex-col gap-5" noValidate>
      {profile && <input type="hidden" name="id" value={profile.id} />}

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-medium">Sprache und Ansprache</h2>
          {profile && <Badge>Version {profile.version}</Badge>}
        </div>
        <Field label="Name des Profils" htmlFor="name" required error={state.errors.name}>
          <Input id="name" name="name" defaultValue={profile?.name ?? ""} placeholder="z. B. PLACEMedia Podcast" required />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Anrede" htmlFor="address" hint="Wie sprechen Captions und Hooks das Publikum an?">
            <Select id="address" name="address" defaultValue={profile?.address ?? "du"}>
              <option value="du">du</option>
              <option value="sie">Sie</option>
            </Select>
          </Field>
          <Field label="Land" htmlFor="country" hint="Beeinflusst Rechtschreibung, Währung und Datumsformat.">
            <Select id="country" name="country" defaultValue={profile?.country ?? "AT"}>
              <option value="DE">Deutschland</option>
              <option value="AT">Österreich</option>
              <option value="CH">Schweiz</option>
            </Select>
          </Field>
          <Field label="Gender-Modus" htmlFor="gender_mode">
            <Select id="gender_mode" name="gender_mode" defaultValue={profile?.gender_mode ?? "neutral"}>
              <option value="neutral">neutral (Mitarbeitende)</option>
              <option value="paarform">Paarform (Mitarbeiterinnen und Mitarbeiter)</option>
              <option value="doppelpunkt">Doppelpunkt (Mitarbeiter:innen)</option>
              <option value="stern">Stern (Mitarbeiter*innen)</option>
              <option value="keine">keine Anpassung</option>
            </Select>
          </Field>
          <Field
            label="ASR-Variante"
            htmlFor="asr_variant"
            hint={
              <span className="inline-flex flex-wrap items-center gap-2">
                <Badge tone="attention" className="h-5 px-2 text-[10px]">
                  de-CH Beta
                </Badge>
                Schweizerdeutsch wird erkannt, aber mit geringerer Konfidenz. Der Editor zeigt einen Hinweis, wenn CH-Marker ohne CH-Modell auftauchen.
              </span>
            }
          >
            <Select id="asr_variant" name="asr_variant" defaultValue={profile?.asr_variant ?? "de"}>
              <option value="de">Deutsch (DE/AT)</option>
              <option value="de-CH">Schweizerdeutsch (Beta)</option>
            </Select>
          </Field>
        </div>
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Ausgabe</h2>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Standard-Plattform" htmlFor="default_platform">
            <Select id="default_platform" name="default_platform" defaultValue={profile?.default_platform ?? "linkedin"}>
              <option value="linkedin">LinkedIn</option>
              <option value="tiktok">TikTok</option>
              <option value="reels">Instagram Reels</option>
              <option value="shorts">YouTube Shorts</option>
            </Select>
          </Field>
          <Field
            label="Caption-Text"
            htmlFor="caption_text_field"
            hint="Schweizerdeutsch-Beta: Original nimmt den gesprochenen Wortlaut, Standard die hochdeutsche Form (text_norm), wo das CH-Modell oder das Lexikon sie sicher liefert. Geschützte Begriffe bleiben immer im Original."
          >
            <Select id="caption_text_field" name="caption_text_field" defaultValue={style.caption_text_field ?? "text"}>
              <option value="text">Original (text)</option>
              <option value="text_norm">Standard (text_norm)</option>
            </Select>
          </Field>
          <Field
            label="Untertitel-Stil"
            htmlFor="caption_preset"
            hint="Automatisch heißt: im Hochformat kommt ein Wort nach dem anderen, im Querformat bleiben die Untertitel ruhig mit zwei Zeilen. Wähle nur dann selbst, wenn du für alle Clips denselben Stil willst."
          >
            {/* Leerer Wert = NULL in der Datenbank = keine ausdrückliche Wahl (Migration 0007) */}
            <Select id="caption_preset" name="caption_preset" defaultValue={profile?.caption_preset ?? ""}>
              <option value="">Automatisch, passend zum Format</option>
              <option value="tiktok_words">Ein Wort nach dem anderen, sehr groß (TikTok)</option>
              <option value="reels_words">Ein Wort nach dem anderen, groß (Reels)</option>
              <option value="shorts_words">Ein Wort nach dem anderen, groß (Shorts)</option>
              <option value="tiktok_bold">Zwei Zeilen, fett mit Rand (TikTok)</option>
              <option value="reels_clean">Zwei Zeilen, schlicht (Reels)</option>
              <option value="shorts_clean">Zwei Zeilen, schlicht (Shorts)</option>
              <option value="linkedin_static">Zwei Zeilen, ruhig auf Fläche (LinkedIn)</option>
              <option value="corporate_third">Bauchbinde unten, ruhig und klein</option>
            </Select>
          </Field>
        </div>
        <Field
          label="Ton-Adjektive"
          htmlFor="tone_adjectives"
          hint="Höchstens drei, z. B. ruhig, konkret, belegt."
          error={state.errors.tone_adjectives}
        >
          <TagInput id="tone_adjectives" name="tone_adjectives" defaultValue={profile?.tone_adjectives ?? []} max={3} />
        </Field>
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <h2 className="text-lg font-medium">Wörterbuch</h2>
        <Field
          label="Marken-Wörterbuch"
          htmlFor="brand_vocab"
          hint="Eigennamen, Produkte, Personen. Werden als Hotwords an die Transkription gegeben und nachkorrigiert."
        >
          <TagInput id="brand_vocab" name="brand_vocab" defaultValue={profile?.brand_vocab ?? []} placeholder="z. B. PLACEMedia" />
        </Field>
        <Field
          label="Geschützte Begriffe"
          htmlFor="protected_terms"
          hint="Austriazismen und Helvetismen wie Jänner, Marille oder Velo werden nie zu Bundesdeutsch korrigiert."
        >
          <TagInput id="protected_terms" name="protected_terms" defaultValue={profile?.protected_terms ?? []} placeholder="z. B. Jänner" />
        </Field>
        <Field label="Gesperrte Phrasen" htmlFor="banned_phrases" hint="Tauchen weder in Hooks noch in Captions auf.">
          <TagInput id="banned_phrases" name="banned_phrases" defaultValue={profile?.banned_phrases ?? []} placeholder="z. B. Game Changer" />
        </Field>
      </GlassCard>

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div>
          <h2 className="text-lg font-medium">CI</h2>
          <p className="mt-1 text-sm text-text-2">
            Farben und Bauchbinde für die Kunden-Clips. Das Design der App bleibt davon unberührt.
          </p>
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <ColorField id="ci_primary" name="ci_primary" label="Primärfarbe" defaultValue={ci.colors?.primary ?? ""} error={state.errors.ci_primary} />
          <ColorField id="ci_secondary" name="ci_secondary" label="Sekundärfarbe" defaultValue={ci.colors?.secondary ?? ""} error={state.errors.ci_secondary} />
          <ColorField id="ci_accent" name="ci_accent" label="Akzentfarbe" defaultValue={ci.colors?.accent ?? ""} error={state.errors.ci_accent} />
          <ColorField
            id="caption_highlight"
            name="caption_highlight"
            label="Caption-Highlight"
            defaultValue={style.highlight_color ?? ""}
            hint="Farbe des betonten Worts bei tiktok_bold, reels_clean und shorts_clean."
            error={state.errors.caption_highlight}
          />
        </div>

        <div className="flex flex-col gap-4 rounded-inner border border-line p-4">
          <Toggle
            checked={lowerThird}
            onChange={setLowerThird}
            name="lower_third_enabled"
            label="Bauchbinde anzeigen"
            description="Name und Funktion in den ersten Sekunden, Preset corporate_third."
          />
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Name" htmlFor="lower_third_name">
              <Input id="lower_third_name" name="lower_third_name" defaultValue={ci.lower_third?.name ?? ""} placeholder="z. B. Ferdinand Platz" disabled={!lowerThird} />
            </Field>
            <Field label="Funktion" htmlFor="lower_third_role">
              <Input id="lower_third_role" name="lower_third_role" defaultValue={ci.lower_third?.role ?? ""} placeholder="z. B. Geschäftsführer" disabled={!lowerThird} />
            </Field>
          </div>
        </div>

        <fieldset className="flex flex-col gap-3">
          <legend className="text-sm font-medium text-text">Hook-Overlay als Standard</legend>
          <p className="text-sm text-text-2">On-Screen-Hook in den ersten 3 Sekunden. Je Plattform an oder aus, im Hook-Studio änderbar.</p>
          <div className="grid gap-3 sm:grid-cols-2">
            {PLATFORMS.map((p) => (
              <Toggle
                key={p}
                checked={hookOverlay[p]}
                onChange={(next) => setHookOverlay((cur) => ({ ...cur, [p]: next }))}
                name={`hook_overlay_${p}`}
                label={PLATFORM_LABELS[p]}
              />
            ))}
          </div>
        </fieldset>

      </GlassCard>

      <AssetsCard profileId={profile?.id ?? null} assets={assets} ci={ci} canUpload={canUploadAssets} />

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className={state.ok ? "text-sm text-text" : "text-sm text-attention"} role="status" aria-live="polite">
          {state.message}
        </p>
        <Button type="submit" disabled={pending}>
          {pending ? "Wird gespeichert" : "Speichern"}
        </Button>
      </div>
    </form>
  );
}
