"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { TagInput } from "@/components/ui/TagInput";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import type { BrandProfile } from "@/lib/repo/types";
import { saveBrandProfileAction, type BrandFormState } from "./actions";

const initialState: BrandFormState = { ok: false, message: "", errors: {} };

export function BrandForm({ profile }: { profile: BrandProfile | null }) {
  const [state, action, pending] = useActionState(saveBrandProfileAction, initialState);

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
            hint="de-CH ist Beta: Schweizerdeutsch wird erkannt, aber mit geringerer Konfidenz."
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
          <Field label="Caption-Preset" htmlFor="caption_preset">
            <Select id="caption_preset" name="caption_preset" defaultValue={profile?.caption_preset ?? "linkedin_static"}>
              <option value="linkedin_static">LinkedIn statisch</option>
              <option value="tiktok_bold">TikTok fett</option>
              <option value="reels_clean">Reels clean</option>
              <option value="shorts_clean">Shorts clean</option>
              <option value="corporate_third">Corporate Bauchbinde</option>
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
