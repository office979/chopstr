"use client";

import { useActionState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Field, Input, Select } from "@/components/ui/Field";
import { TagInput } from "@/components/ui/TagInput";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ColorField } from "@/components/ui/ColorField";
import { Toggle } from "@/components/ui/Toggle";
import type { BrandAsset, BrandProfile, CaptionPreset, Platform } from "@/lib/repo/types";
import type { CaptionStyleExt } from "@/lib/repo/types-api";
import type { PreviewFont } from "@/components/clips/SilentPreview";
import { AssetsCard } from "./AssetsCard";
import { Beispielszene } from "./Beispielszene";
import { PLATFORMS, PLATFORM_LABELS } from "@/lib/clips/labels";
import { useMemo, useState } from "react";
import { befundSatz, pruefen as regelnPruefen } from "@/lib/brand/wortregeln";
import { saveBrandProfileAction, type BrandFormState } from "./actions";

const initialState: BrandFormState = { ok: false, message: "", errors: {} };

export function BrandForm({
  profile,
  assets,
  canUploadAssets,
  vorschauSchrift,
  clipsMitProfil,
}: {
  profile: BrandProfile | null;
  assets: BrandAsset[];
  canUploadAssets: boolean;
  /* Die hochgeladene Marken-Schrift, damit die Beispielszene sie zeigt. */
  vorschauSchrift: PreviewFont | null;
  /* Wie viele gebaute Clips dieses Profil schon verwendet haben. Daran hängt der Satz darüber,
   * was eine Änderung bewirkt. */
  clipsMitProfil: number;
}) {
  const [state, action, pending] = useActionState(saveBrandProfileAction, initialState);
  const ci = profile?.ci ?? {};
  const style: CaptionStyleExt = profile?.caption_style ?? {};
  const [lowerThird, setLowerThird] = useState(ci.lower_third?.enabled ?? false);
  const [fein, setFein] = useState(false);

  /* Die Beispielszene reagiert auf die Eingaben, deshalb liegen die dafür nötigen Werte im
   * Zustand und nicht nur im Formular. Alles andere bleibt bei defaultValue: es zeigt sich
   * ohnehin erst im fertigen Clip. */
  const [plattform, setPlattform] = useState<Platform>(profile?.default_platform ?? "linkedin");
  const [preset, setPreset] = useState<string>(profile?.caption_preset ?? "");
  const [highlight, setHighlight] = useState(style.highlight_color ?? "");
  const [bbName, setBbName] = useState(ci.lower_third?.name ?? "");
  const [bbRolle, setBbRolle] = useState(ci.lower_third?.role ?? "");
  const [merken, setMerken] = useState<string[]>(profile?.brand_vocab ?? []);
  const [behalten, setBehalten] = useState<string[]>(profile?.protected_terms ?? []);
  const [vermeiden, setVermeiden] = useState<string[]>(profile?.banned_phrases ?? []);

  const befunde = useMemo(
    () => regelnPruefen({ merken, behalten, vermeiden }),
    [merken, behalten, vermeiden],
  );

  const logoAsset = assets.find((a) => a.id === ci.logo_asset_id) ?? null;
  const logoUrl = profile && logoAsset ? `/api/brand/${profile.id}/assets/${logoAsset.id}` : null;
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
          <div>
            <p className="text-xs uppercase tracking-wide text-text-3">Schritt 2 von 3</p>
            <h2 className="mt-0.5 text-lg font-medium">Sprache und Ansprache</h2>
          </div>
          {profile && <Badge>Fassung {profile.version}</Badge>}
        </div>
        <Field label="Name des Profils" htmlFor="name" required error={state.errors.name}>
          <Input id="name" name="name" defaultValue={profile?.name ?? ""} placeholder="z. B. PLACEMedia Podcast" required />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Anrede" htmlFor="address" hint="Wie der Text in deinen Clips das Publikum anspricht.">
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
          <Field
            label="Geschlechterformen"
            htmlFor="gender_mode"
            hint="Wie im Text über Gruppen von Menschen geschrieben wird."
          >
            <Select id="gender_mode" name="gender_mode" defaultValue={profile?.gender_mode ?? "neutral"}>
              <option value="neutral">neutral (Mitarbeitende)</option>
              <option value="paarform">Paarform (Mitarbeiterinnen und Mitarbeiter)</option>
              <option value="doppelpunkt">Doppelpunkt (Mitarbeiter:innen)</option>
              <option value="stern">Stern (Mitarbeiter*innen)</option>
              <option value="keine">keine Anpassung</option>
            </Select>
          </Field>
          <Field
            label="Gesprochene Sprache"
            htmlFor="asr_variant"
            hint="Was in deinen Videos gesprochen wird. Danach richtet sich, wie der Computer zuhört."
          >
            <Select id="asr_variant" name="asr_variant" defaultValue={profile?.asr_variant ?? "de"}>
              <option value="de">Deutsch</option>
              <option value="de-CH">Schweizerdeutsch</option>
            </Select>
          </Field>
          {/* Gesprochene Sprache und geschriebene Form sind zwei Fragen. Wer Schweizerdeutsch
            * spricht, will die Untertitel vielleicht trotzdem auf Hochdeutsch. Vorher stand das
            * als „Caption-Text: Original (text) / Standard (text_norm)" unter „Ausgabe", also
            * weit weg von der Sprache und in der Sprache der Datenbank. */}
          <Field
            label="Schreibweise der Untertitel"
            htmlFor="caption_text_field"
            hint={'Wortlaut heißt: es steht da, wie es gesagt wurde. Hochdeutsch heißt: Mundart wird in die Schriftform gebracht, wo das sicher geht. Wörter aus „Nicht verändern“ bleiben immer, wie sie sind.'}
          >
            <Select id="caption_text_field" name="caption_text_field" defaultValue={style.caption_text_field ?? "text"}>
              <option value="text">So, wie es gesagt wurde</option>
              <option value="text_norm">In Hochdeutsch</option>
            </Select>
          </Field>
        </div>
        <p className="text-sm text-text-2">
          Schweizerdeutsch erkennt der Computer weniger sicher als Deutsch. Im Text eines Clips
          steht dann ein Hinweis an den Stellen, an denen er sich nicht sicher war.
        </p>
      </GlassCard>

      {/* Schritt 3: wie der Clip aussieht. Links die Entscheidungen, rechts das Bild dazu.
          Vorher standen hier Farbwähler und Schalter ohne Bild; ob das zusammen funktioniert,
          sah man erst am fertigen Clip. */}
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div>
          <p className="text-xs uppercase tracking-wide text-text-3">Schritt 3 von 3</p>
          <h2 className="mt-0.5 text-lg font-medium">Clip-Stil</h2>
          <p className="mt-1 text-sm text-text-2">
            So sehen deine Clips aus. Das Aussehen der App bleibt davon unberührt.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px] lg:items-start">
          <div className="flex flex-col gap-5">
            <Field
              label="Wofür vor allem"
              htmlFor="default_platform"
              hint="Danach richtet sich das Format der Vorschau und was voreingestellt ist."
            >
              <Select
                id="default_platform"
                name="default_platform"
                value={plattform}
                onChange={(e) => setPlattform(e.target.value as Platform)}
              >
                <option value="linkedin">LinkedIn</option>
                <option value="tiktok">TikTok</option>
                <option value="reels">Instagram Reels</option>
                <option value="shorts">YouTube Shorts</option>
              </Select>
            </Field>

            <Field
              label="Untertitel"
              htmlFor="caption_preset"
              hint="Automatisch heißt: hochkant kommt ein Wort nach dem anderen, quer bleiben die Untertitel ruhig mit zwei Zeilen."
            >
              <Select id="caption_preset" name="caption_preset" value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="">Automatisch, passend zum Format</option>
                <option value="tiktok_words">Ein Wort nach dem anderen, sehr groß</option>
                <option value="reels_words">Ein Wort nach dem anderen, groß</option>
                <option value="tiktok_bold">Zwei Zeilen, fett mit Rand</option>
                <option value="reels_clean">Zwei Zeilen, schlicht</option>
                <option value="linkedin_static">Zwei Zeilen, ruhig auf Fläche</option>
                <option value="corporate_third">Bauchbinde unten, ruhig und klein</option>
              </Select>
            </Field>

            <ColorField
              id="caption_highlight"
              name="caption_highlight"
              label="Farbe des betonten Worts"
              defaultValue={style.highlight_color ?? ""}
              onChange={setHighlight}
              hint="Nur bei den Stilen, die ein Wort hervorheben."
              error={state.errors.caption_highlight}
            />

            <div className="flex flex-col gap-4 rounded-inner border border-line p-4">
              <Toggle
                checked={lowerThird}
                onChange={setLowerThird}
                name="lower_third_enabled"
                label="Name einblenden"
                description="Name und Funktion in den ersten Sekunden, unten im Bild."
              />
              <div className="grid gap-5 sm:grid-cols-2">
                <Field label="Name" htmlFor="lower_third_name">
                  <Input
                    id="lower_third_name"
                    name="lower_third_name"
                    value={bbName}
                    onChange={(e) => setBbName(e.target.value)}
                    placeholder="z. B. Ferdinand Platz"
                    disabled={!lowerThird}
                  />
                </Field>
                <Field label="Funktion" htmlFor="lower_third_role">
                  <Input
                    id="lower_third_role"
                    name="lower_third_role"
                    value={bbRolle}
                    onChange={(e) => setBbRolle(e.target.value)}
                    placeholder="z. B. Geschäftsführer"
                    disabled={!lowerThird}
                  />
                </Field>
              </div>
            </div>
          </div>

          <div className="lg:sticky lg:top-8">
            <p className="mb-2 text-sm font-medium text-text">So sieht ein Clip aus</p>
            <Beispielszene
              plattform={plattform}
              preset={(preset || undefined) as CaptionPreset | undefined ?? "linkedin_static"}
              hookText={style.hook_overlay?.[plattform] ?? plattform !== "linkedin" ? "Der teuerste Fehler" : null}
              bauchbinde={lowerThird ? { name: bbName, role: bbRolle } : null}
              highlightColor={highlight || undefined}
              font={vorschauSchrift}
              logoUrl={logoUrl}
              logoAn={ci.watermark?.enabled ?? false}
            />
          </div>
        </div>
      </GlassCard>

      {/* Wörter und Schreibweisen: drei Listen mit drei Wirkungen, jede mit Beispiel. Vorher
          hiessen sie „Marken-Wörterbuch", „Geschützte Begriffe" und „Gesperrte Phrasen", und
          worin sie sich unterscheiden, stand nirgends. */}
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div>
          <h2 className="text-lg font-medium">Wörter und Schreibweisen</h2>
          <p className="mt-1 text-sm text-text-2">
            Damit Namen richtig geschrieben werden und bestimmte Formulierungen nicht vorkommen.
          </p>
        </div>

        {befunde.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded-inner border border-attention/50 bg-attention/10 p-3">
            <p className="text-sm font-medium text-text">
              {befunde.length === 1 ? "Eine Regel passt nicht" : `${befunde.length} Regeln passen nicht`}
            </p>
            <ul className="flex flex-col gap-1">
              {befunde.slice(0, 5).map((b, i) => (
                <li key={i} className="text-sm text-text-2">
                  {befundSatz(b)}
                </li>
              ))}
            </ul>
          </div>
        )}

        <Field
          label="So schreiben"
          htmlFor="brand_vocab"
          hint="Namen, Produkte, Personen. Der Computer hört genauer hin und schreibt sie genau so. Beispiel: PLACEMedia."
        >
          <TagInput
            id="brand_vocab"
            name="brand_vocab"
            defaultValue={profile?.brand_vocab ?? []}
            onChange={setMerken}
            placeholder="z. B. PLACEMedia"
          />
        </Field>
        <Field
          label="Nicht verändern"
          htmlFor="protected_terms"
          hint="Wörter, die so bleiben, wie sie gesprochen wurden. Beispiel: Jänner bleibt Jänner und wird nicht zu Januar."
        >
          <TagInput
            id="protected_terms"
            name="protected_terms"
            defaultValue={profile?.protected_terms ?? []}
            onChange={setBehalten}
            placeholder="z. B. Jänner"
          />
        </Field>
        <Field
          label="Nicht verwenden"
          htmlFor="banned_phrases"
          hint="Formulierungen, die weder im Einstieg noch in den Untertiteln auftauchen. Beispiel: Game Changer."
        >
          <TagInput
            id="banned_phrases"
            name="banned_phrases"
            defaultValue={profile?.banned_phrases ?? []}
            onChange={setVermeiden}
            placeholder="z. B. Game Changer"
          />
        </Field>
      </GlassCard>

      {/* Alles Weitere zugeklappt: es entscheidet niemand beim Einrichten, und offen macht es
          aus drei Schritten eine Wand. */}
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <button
          type="button"
          onClick={() => setFein((v) => !v)}
          aria-expanded={fein}
          className="transition-soft self-start text-sm text-text-2 underline underline-offset-4 hover:text-text"
        >
          {fein ? "Fein einstellen schließen" : "Fein einstellen"}
        </button>

        {fein && (
          <div className="flex flex-col gap-5">
            <Field label="Tonfall" htmlFor="tone_adjectives" hint="Höchstens drei Wörter, zum Beispiel ruhig, konkret, belegt." error={state.errors.tone_adjectives}>
              <TagInput id="tone_adjectives" name="tone_adjectives" defaultValue={profile?.tone_adjectives ?? []} max={3} />
            </Field>

            {/* Diese drei Farben sind heute reine Notizen: weder die App noch der Renderer lesen
                sie (geprüft in activities/render.py und in der ganzen Oberfläche). Sie stehen hier,
                weil die Daten vorhanden sind und niemand sie verlieren soll - aber sie als
                Einstellung auszugeben, die etwas bewirkt, wäre falsch. Die Farbe, die im Clip
                wirklich ankommt, ist „Farbe des betonten Worts" weiter oben. */}
            <div className="flex flex-col gap-3">
              <div>
                <p className="text-sm font-medium text-text">Markenfarben notieren</p>
                <p className="mt-0.5 text-sm text-text-2">
                  {'Zum Festhalten für dein Team. Sie ändern im Moment nichts am Aussehen der Clips; dafür ist „Farbe des betonten Worts“ zuständig.'}
                </p>
              </div>
              <div className="grid gap-5 sm:grid-cols-2">
                <ColorField id="ci_primary" name="ci_primary" label="Hauptfarbe" defaultValue={ci.colors?.primary ?? ""} error={state.errors.ci_primary} />
                <ColorField id="ci_secondary" name="ci_secondary" label="Zweitfarbe" defaultValue={ci.colors?.secondary ?? ""} error={state.errors.ci_secondary} />
                <ColorField id="ci_accent" name="ci_accent" label="Akzentfarbe" defaultValue={ci.colors?.accent ?? ""} error={state.errors.ci_accent} />
              </div>
            </div>

            <fieldset className="flex flex-col gap-3">
              <legend className="text-sm font-medium text-text">Einstieg als Text im Bild</legend>
              <p className="text-sm text-text-2">
                Ein kurzer Satz in den ersten drei Sekunden. Je Plattform an oder aus, im Clip änderbar.
              </p>
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
          </div>
        )}
      </GlassCard>

      <AssetsCard profileId={profile?.id ?? null} assets={assets} ci={ci} canUpload={canUploadAssets} />

      {/* Was das Speichern bewirkt, bevor jemand es drückt. Gebaute Clips tragen ihren eigenen
          Plan; eine Änderung hier greift erst beim nächsten Bauen. Das ist kein Mangel, sondern
          der Grund dafür, dass ein freigegebener Clip nicht über Nacht anders aussieht. */}
      <GlassCard padding="md" className="flex flex-col gap-2">
        <p className="text-sm font-medium text-text">Was ändert sich damit?</p>
        <p className="text-sm text-text-2">
          Neue Clips bekommen dieses Aussehen sofort.{" "}
          {clipsMitProfil > 0
            ? `${clipsMitProfil === 1 ? "Ein Projekt nutzt" : `${clipsMitProfil} Projekte nutzen`} dieses Profil. Schon gebaute Clips behalten ihr Aussehen, bis du sie einzeln neu bauen lässt.`
            : "Schon gebaute Clips behalten ihr Aussehen, bis du sie einzeln neu bauen lässt."}
        </p>
      </GlassCard>

      <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
        <p className={state.ok ? "text-sm text-text" : "text-sm text-attention"} role="status" aria-live="polite">
          {state.message}
        </p>
        <Button type="submit" disabled={pending || befunde.some((b) => b.art === "widerspruch")}>
          {pending ? "Wird gespeichert" : "Speichern"}
        </Button>
      </div>
    </form>
  );
}
