"use client";

import { useActionState, useEffect } from "react";
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
import Link from "next/link";
import { cn } from "@/components/ui/cn";
import { setzeUngespeichert } from "@/lib/brand/ungespeichert";
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
  betroffeneVideos,
}: {
  profile: BrandProfile | null;
  assets: BrandAsset[];
  canUploadAssets: boolean;
  /* Die hochgeladene Marken-Schrift, damit die Beispielszene sie zeigt. */
  vorschauSchrift: PreviewFont | null;
  /* Wie viele gebaute Clips dieses Profil schon verwendet haben. Daran hängt der Satz darüber,
   * was eine Änderung bewirkt. */
  /* Die Videos, die diese Marke benutzen. Als Liste und nicht als Zahl: „3 Projekte nutzen dieses
   * Profil" beantwortet nicht die Frage, die man vor dem Speichern hat, nämlich WELCHE. */
  betroffeneVideos: { id: string; titel: string }[];
}) {
  const [state, action, pending] = useActionState(saveBrandProfileAction, initialState);
  /* Ob etwas ungespeichert ist. Gemessen daran, dass jemand ein Feld angefasst hat - nicht an
   * einem Vergleich aller Werte: das Formular hat über dreissig Felder, teils frei gesetzt, und
   * ein halb richtiger Vergleich wäre schlimmer als eine ehrliche Faustregel. */
  const [geaendert, setGeaendert] = useState(false);
  /* Nach einem erfolgreichen Speichern ist nichts mehr offen. Gerechnet und nicht im Effekt
   * gesetzt: ein setState im Effekt löst eine zweite Renderrunde aus. */
  const offen = geaendert && !(state.ok && !pending);

  /* Der Wert wird auch ausserhalb dieses Baums gebraucht: die Markenliste oben fragt ihn, bevor
   * sie auf eine andere Marke wechselt. */
  useEffect(() => {
    setzeUngespeichert(offen);
    return () => setzeUngespeichert(false);
  }, [offen]);

  /* Neuladen oder Schliessen mit offenen Änderungen: der Browser fragt. Für den Wechsel INNERHALB
   * der Seite fragt die Markenliste, die denselben Wert liest. */
  useEffect(() => {
    if (!offen) return undefined;
    const fragen = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", fragen);
    return () => window.removeEventListener("beforeunload", fragen);
  }, [offen]);
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
    <form
      action={action}
      onInput={() => setGeaendert(true)}
      onChange={() => setGeaendert(true)}
      className="flex flex-col gap-5 pb-20"
      noValidate
    >
      {profile && <input type="hidden" name="id" value={profile.id} />}

      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div className="flex items-center justify-between">
          <div>
            {/* Keine Schrittzahlen mehr. „Schritt 2 von 3" verspricht eine Einrichtung mit
                Weiter und Zurück; hier liegt alles auf einer Seite, und wer eine Marke pflegt,
                springt ohnehin zu der Stelle, die er ändern will. Bereiche mit Namen sagen, wo
                man ist, ohne eine Reihenfolge zu behaupten, die es nicht gibt. */}
            <h2 className="text-lg font-medium">Sprache und Ansprache</h2>
          </div>
          {profile && <Badge>Fassung {profile.version}</Badge>}
        </div>
        <Field label="Name der Marke" htmlFor="name" required error={state.errors.name}>
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
          <h2 className="text-lg font-medium">Clip-Stil</h2>
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
        {/* Was diese Liste wirklich tut, nachgesehen im Renderlauf: banned_phrases geht in
            copy_de.lint und in den Prompt für den Posttext. Sie wirkt damit auf Texte, die der
            Computer selbst schreibt - Einstieg und Beitragstext. Untertitel entstehen aus dem
            gesprochenen Wort und werden nicht angefasst.

            Vorher stand hier „weder im Einstieg noch in den Untertiteln". Das war ein
            Versprechen, das die Anwendung nicht hält, und es ging in die gefährlichere Richtung:
            wer sich darauf verlässt, glaubt, ein Wort komme nicht ins Bild. */}
        <Field
          label="Nicht selbst schreiben"
          htmlFor="banned_phrases"
          hint="Formulierungen, die der Computer nicht verwenden soll, wenn er Einstieg oder Beitragstext schreibt. Beispiel: Game Changer. Gesprochene Wörter im Untertitel bleiben unberührt."
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
          Neue Clips bekommen dieses Aussehen sofort. Schon gebaute Clips behalten ihres, bis du
          sie einzeln neu bauen lässt.
        </p>
        {betroffeneVideos.length > 0 && (
          <>
            <p className="mt-1 text-sm text-text-2">
              {betroffeneVideos.length === 1 ? "Dieses Video nutzt die Marke:" : `Diese ${betroffeneVideos.length} Videos nutzen die Marke:`}
            </p>
            <ul className="flex flex-wrap gap-2">
              {betroffeneVideos.map((v) => (
                <li key={v.id}>
                  <Link
                    href={`/projekte/${v.id}/clips`}
                    className="transition-soft inline-block max-w-[280px] truncate rounded-pill border border-line px-3 py-1 text-xs text-text-2 hover:border-line-strong hover:text-text"
                  >
                    {v.titel}
                  </Link>
                </li>
              ))}
            </ul>
          </>
        )}
      </GlassCard>

      {/* Speichern bleibt in Sicht.
          Vorher stand der Knopf ganz unten hinter vier Karten: wer oben eine Farbe änderte, musste
          erst durch die halbe Seite scrollen, um zu erfahren, ob das schon gilt. Jetzt steht am
          unteren Rand, welche Marke bearbeitet wird, ob etwas offen ist, und der Knopf dazu. */}
      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-line bg-[#07070f]/95 backdrop-blur">
        <div className="mx-auto flex max-w-[var(--shell-max,1200px)] flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
          <div className="flex min-w-0 flex-col">
            <span className="truncate text-sm font-medium text-text">
              {profile?.name ?? "Neue Marke"}
            </span>
            <span
              className={cn("text-xs", state.ok || !state.message ? "text-text-3" : "text-attention")}
              role="status"
              aria-live="polite"
            >
              {state.message || (offen ? "Nicht gespeichert" : "Alles gespeichert")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              className="text-sm text-text-2 underline underline-offset-4 hover:text-text"
            >
              Zur Markenübersicht
            </button>
            <Button type="submit" disabled={pending || befunde.some((b) => b.art === "widerspruch")}>
              {pending ? "Wird gespeichert" : offen ? "Änderungen speichern" : "Speichern"}
            </Button>
          </div>
        </div>
      </div>
    </form>
  );
}
