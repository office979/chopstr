"use client";

import Link from "next/link";
import { useCallback, useId, useMemo, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input, Textarea } from "@/components/ui/Field";
import { Toggle } from "@/components/ui/Toggle";
import { cn } from "@/components/ui/cn";
import { SilentPreview } from "@/components/clips/SilentPreview";
import type { CaptionVersion, Clip, HookPattern, HookVersion, Platform, PostCaptions } from "@/lib/repo/types";
import { PLATFORMS, PLATFORM_LABELS, patternLabel } from "@/lib/clips/labels";
import { PLATFORM_DEFAULT_PRESET } from "@/lib/clips/presets";
import { compositionDuration } from "@/lib/clips/render-demo";
import { ONSCREEN_HOOK_MAX_WORDS, SPOKEN_HOOK_MAX_WORDS, countWords, lintCopy, lintHook, type LintProfile } from "@/lib/copy/lint";
import { hookClaimCheck } from "@/lib/copy/claims";
import { formatDateTime } from "@/lib/format";

interface Props {
  sourceId: string;
  clip: Clip;
  clipText: string;
  initialVersions: HookVersion[];
  captions: CaptionVersion | null;
  lintProfile: LintProfile;
  siblingClips: Clip[];
  highlightColor?: string;
  hookOverlayDefault: boolean;
  lowerThird: { name: string; role: string } | null;
}

interface ApiError {
  error?: string;
}

function Notes({ notes, issues }: { notes: string[]; issues: string[] }) {
  if (notes.length === 0 && issues.length === 0) return null;
  return (
    <ul className="flex flex-col gap-1 text-xs">
      {issues.map((i, k) => (
        <li key={`c-${k}`} className="text-attention">
          {i}
        </li>
      ))}
      {notes.map((n, k) => (
        <li key={`n-${k}`} className="text-text-2">
          {n}
        </li>
      ))}
    </ul>
  );
}

function WordCount({ text, max }: { text: string; max: number }) {
  const n = countWords(text);
  return (
    <span className={cn("font-mono text-xs tabular-nums", n > max ? "text-attention" : "text-text-2")}>
      {n} von {max} Wörtern
    </span>
  );
}

/* Hook-Studio: Varianten links, drei Spalten (gesprochen, On-Screen, Post-Caption), Versionen, stumme Vorschau.
 * Linter und Claim-Check laufen live gegen den Clip-Text; Speichern legt eine manuelle Version an. */
export function HookStudio({ sourceId, clip, clipText, initialVersions, captions, lintProfile, siblingClips, highlightColor, hookOverlayDefault, lowerThird }: Props) {
  const [versions, setVersions] = useState<HookVersion[]>(initialVersions);
  const current = versions.length ? versions[versions.length - 1] : null;
  const variants = useMemo(() => [...versions].reverse().find((v) => v.variants.length > 0)?.variants ?? [], [versions]);

  const [selectedVariant, setSelectedVariant] = useState<number | null>(() => {
    if (!current) return null;
    const idx = variants.findIndex((v) => v.spoken === current.spoken_hook && v.onscreen === current.onscreen_hook);
    return idx >= 0 ? idx : null;
  });
  const [spoken, setSpoken] = useState(current?.spoken_hook ?? "");
  const [onscreen, setOnscreen] = useState(current?.onscreen_hook ?? "");
  const [pattern, setPattern] = useState<HookPattern | null>(current?.pattern ?? null);
  const [postCaptions, setPostCaptions] = useState<PostCaptions>(current?.post_captions ?? {});
  const [cta, setCta] = useState(current?.cta ?? "");
  const [tab, setTab] = useState<Platform>(clip.platform);
  const [overlay, setOverlay] = useState(hookOverlayDefault);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [savedVersion, setSavedVersion] = useState<HookVersion | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string; href?: string } | null>(null);
  const spokenId = useId();
  const onscreenId = useId();
  const captionId = useId();
  const ctaId = useId();

  const spokenLint = useMemo(() => lintHook(spoken, "spoken", lintProfile), [spoken, lintProfile]);
  const onscreenLint = useMemo(() => lintHook(onscreen, "onscreen", lintProfile), [onscreen, lintProfile]);
  const spokenClaims = useMemo(() => hookClaimCheck(spoken, clipText), [spoken, clipText]);
  const onscreenClaims = useMemo(() => hookClaimCheck(onscreen, clipText), [onscreen, clipText]);
  const captionText = postCaptions[tab] ?? "";
  const captionLint = useMemo(() => lintCopy(captionText, lintProfile), [captionText, lintProfile]);
  const captionClaims = useMemo(() => hookClaimCheck(captionText, clipText), [captionText, clipText]);

  const dirty =
    !current ||
    spoken !== (current.spoken_hook ?? "") ||
    onscreen !== (current.onscreen_hook ?? "") ||
    pattern !== current.pattern ||
    cta !== (current.cta ?? "") ||
    PLATFORMS.some((p) => (postCaptions[p] ?? "") !== (current.post_captions[p] ?? ""));

  const pickVariant = (idx: number) => {
    const v = variants[idx];
    if (!v) return;
    setSelectedVariant(idx);
    setSpoken(v.spoken);
    setOnscreen(v.onscreen);
    setPattern(v.pattern);
    setSavedVersion(null);
  };

  const save = useCallback(async () => {
    setSaving(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/hooks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spoken_hook: spoken, onscreen_hook: onscreen, pattern, post_captions: postCaptions, cta }),
      });
      const data = (await res.json()) as ApiError & { hook?: HookVersion };
      if (!res.ok || !data.hook) throw new Error(data.error ?? "Speichern fehlgeschlagen");
      setVersions((prev) => [...prev, data.hook!]);
      setSavedVersion(data.hook);
      setSpoken(data.hook.spoken_hook ?? "");
      setOnscreen(data.hook.onscreen_hook ?? "");
      setMessage({ tone: "ok", text: `Version ${data.hook.version} gespeichert (manuell).` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Speichern fehlgeschlagen" });
    } finally {
      setSaving(false);
    }
  }, [sourceId, clip.id, spoken, onscreen, pattern, postCaptions, cta]);

  const rerender = useCallback(async () => {
    setRendering(true);
    setMessage(null);
    try {
      const res = await fetch(`/api/projects/${sourceId}/clips/${clip.id}/render`, { method: "POST" });
      const data = (await res.json()) as ApiError & { signaled?: boolean; demo?: boolean };
      if (!res.ok) throw new Error(data.error ?? "Render konnte nicht angestoßen werden");
      setSavedVersion(null);
      setMessage({
        tone: "ok",
        text: data.signaled ? "Render angestoßen." : data.demo ? "Demo-Render läuft." : "Render vorgemerkt, startet sobald der Worker erreichbar ist.",
        href: `/projekte/${sourceId}/clips`,
      });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Render konnte nicht angestoßen werden" });
    } finally {
      setRendering(false);
    }
  }, [sourceId, clip.id]);

  const duration = clip.duration_s ?? compositionDuration(clip);
  const canSave = !saving && dirty && (spoken.trim() || onscreen.trim());

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px] xl:items-start">
      <div className="flex flex-col gap-5">
        <div className="grid gap-5 lg:grid-cols-[280px_minmax(0,1fr)] lg:items-start">
          {/* Varianten */}
          <GlassCard padding="md" className="flex flex-col gap-3">
            <div>
              <h2 className="text-sm font-medium">Fünf Varianten</h2>
              <p className="mt-0.5 text-xs text-text-2">
                {current?.origin === "llm" ? `${current.model_id ?? "Sprachmodell"}` : "Aus Version 1 (Sprachmodell)"}. Auswahl übernimmt die Texte.
              </p>
            </div>
            {variants.length === 0 ? (
              <p className="text-sm text-text-2">Noch keine Varianten. Sie entstehen beim ersten Render (Copy zuerst).</p>
            ) : (
              <ul className="flex flex-col gap-2" aria-label="Hook-Varianten">
                {variants.map((v, i) => {
                  const active = selectedVariant === i;
                  return (
                    <li key={`${v.pattern}-${i}`}>
                      <button
                        type="button"
                        onClick={() => pickVariant(i)}
                        aria-pressed={active}
                        className={cn(
                          "transition-soft w-full rounded-inner border p-3 text-left hover:border-line-strong",
                          active ? "glass-selected border-ai-soft/50" : "border-line",
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <Badge tone={active ? "ai" : "neutral"} className="h-6 px-2.5 text-[11px]">
                            {patternLabel(v.pattern)}
                          </Badge>
                          <span className="font-mono text-[11px] tabular-nums text-text-3">
                            {countWords(v.spoken)}/{countWords(v.onscreen)} W
                          </span>
                        </div>
                        <p className="mt-2 text-sm text-text">{v.spoken}</p>
                        <p className="mt-1 text-xs text-text-2">On-Screen: {v.onscreen}</p>
                        <div className="mt-2">
                          <Notes notes={v.lint_notes} issues={v.claim_issues} />
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </GlassCard>

          {/* Drei Spalten */}
          <GlassCard padding="lg" className="flex flex-col gap-6">
            <div className="grid gap-6 md:grid-cols-3">
              <div className="flex flex-col gap-2">
                <label htmlFor={spokenId} className="text-sm font-medium">
                  Gesprochener Hook
                </label>
                <Textarea id={spokenId} value={spoken} onChange={(e) => setSpoken(e.target.value)} className="min-h-28" aria-invalid={spokenClaims.length > 0 || undefined} />
                <WordCount text={spoken} max={SPOKEN_HOOK_MAX_WORDS} />
                <Notes notes={spokenLint.notes.filter((n) => !n.includes("Wörter, erlaubt"))} issues={spokenClaims} />
              </div>
              <div className="flex flex-col gap-2">
                <label htmlFor={onscreenId} className="text-sm font-medium">
                  On-Screen-Hook
                </label>
                <Textarea id={onscreenId} value={onscreen} onChange={(e) => setOnscreen(e.target.value)} className="min-h-28" aria-invalid={onscreenClaims.length > 0 || undefined} />
                <WordCount text={onscreen} max={ONSCREEN_HOOK_MAX_WORDS} />
                <Notes notes={onscreenLint.notes.filter((n) => !n.includes("Wörter, erlaubt"))} issues={onscreenClaims} />
                <Toggle checked={overlay} onChange={setOverlay} label="Als Overlay einblenden" description="Erste 3 Sekunden, oben in der Safe Zone (Vorschau)." />
              </div>
              <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <label htmlFor={captionId} className="text-sm font-medium">
                    Post-Caption
                  </label>
                  <div className="flex gap-1" role="tablist" aria-label="Plattform">
                    {PLATFORMS.map((p) => (
                      <button
                        key={p}
                        type="button"
                        role="tab"
                        aria-selected={tab === p}
                        onClick={() => setTab(p)}
                        className={cn(
                          "transition-soft h-7 rounded-pill border px-2.5 text-[11px]",
                          tab === p ? "border-white/40 bg-white/10 text-text" : "border-line text-text-2 hover:text-text",
                        )}
                      >
                        {PLATFORM_LABELS[p]}
                      </button>
                    ))}
                  </div>
                </div>
                <Textarea
                  id={captionId}
                  value={captionText}
                  onChange={(e) => setPostCaptions((cur) => ({ ...cur, [tab]: e.target.value }))}
                  className="min-h-28"
                  placeholder={`Caption für ${PLATFORM_LABELS[tab]}`}
                />
                <span className="font-mono text-xs tabular-nums text-text-2">{captionText.length} Zeichen</span>
                <Notes notes={captionLint.notes} issues={captionClaims} />
                <label htmlFor={ctaId} className="mt-2 text-sm font-medium">
                  CTA
                </label>
                <Input id={ctaId} value={cta} onChange={(e) => setCta(e.target.value)} placeholder="z. B. Ganze Folge im Profil" />
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3 border-t border-line pt-5">
              <Button onClick={save} disabled={!canSave}>
                {saving ? "Wird gespeichert" : "Speichern"}
              </Button>
              <span className="text-sm text-text-2">Muster: {patternLabel(pattern)}</span>
              {message && (
                <p role="status" aria-live="polite" className={cn("text-sm", message.tone === "ok" ? "text-text" : "text-attention")}>
                  {message.text}
                  {message.href && (
                    <>
                      {" "}
                      <Link href={message.href} className="font-medium underline-offset-4 hover:underline">
                        Clips ansehen
                      </Link>
                    </>
                  )}
                </p>
              )}
            </div>

            {savedVersion && (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-inner border border-line-strong p-4">
                <p className="text-sm text-text">
                  Version {savedVersion.version} ist gespeichert. Für das Video neu rendern, damit Overlay und Captions den neuen Hook zeigen.
                  {siblingClips.length > 0 && (
                    <span className="block text-text-2">
                      Weitere Clips dieses Kandidaten ({siblingClips.map((s) => PLATFORM_LABELS[s.platform]).join(", ")}) haben eigene Hook-Versionen.
                    </span>
                  )}
                </p>
                <Button size="sm" onClick={rerender} disabled={rendering}>
                  {rendering ? "Wird angestoßen" : "Neu rendern"}
                </Button>
              </div>
            )}
          </GlassCard>
        </div>

        {/* Versionen */}
        <GlassCard padding="md">
          <h2 className="mb-3 text-sm font-medium">Versionen</h2>
          {versions.length === 0 ? (
            <p className="text-sm text-text-2">Noch keine Hook-Version. Version 1 entsteht beim ersten Render.</p>
          ) : (
            <ol className="flex flex-col gap-2">
              {[...versions].reverse().map((v) => (
                <li key={v.id} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                  <span className="font-mono text-text">v{v.version}</span>
                  <Badge tone={v.origin === "llm" ? "ai" : "ok"} className="h-6 px-2.5 text-[11px]">
                    {v.origin === "llm" ? "Sprachmodell" : "manuell"}
                  </Badge>
                  <span className="text-text-2">{patternLabel(v.pattern)}</span>
                  <span className="font-mono text-xs text-text-3">
                    {v.model_id ?? "ohne Modell"}
                    {v.prompt_version ? ` · ${v.prompt_version}` : ""} · {formatDateTime(v.created_at)}
                  </span>
                  {v.claim_issues.length > 0 && <span className="text-xs text-attention">{v.claim_issues.length} Claim-Issues</span>}
                  {v.lint_notes.length > 0 && <span className="text-xs text-text-2">{v.lint_notes.length} Lint-Hinweise</span>}
                </li>
              ))}
            </ol>
          )}
        </GlassCard>
      </div>

      {/* Stumme Vorschau */}
      <GlassCard padding="md" id="vorschau" className="flex flex-col gap-3">
        <div>
          <h2 className="text-sm font-medium">Ton-aus-Vorschau</h2>
          <p className="mt-0.5 text-xs text-text-2">
            {PLATFORM_LABELS[clip.platform]}, {clip.aspect}, Preset {captions?.preset ?? clip.render_plan?.captions.preset ?? PLATFORM_DEFAULT_PRESET[clip.platform]}
          </p>
        </div>
        <SilentPreview
          aspect={clip.aspect}
          preset={captions?.preset ?? clip.render_plan?.captions.preset ?? PLATFORM_DEFAULT_PRESET[clip.platform]}
          durationS={duration}
          cards={captions?.cards ?? []}
          hookText={overlay ? onscreen.trim() || null : null}
          titleCard={clip.title_card}
          highlightColor={highlightColor}
          lowerThird={lowerThird}
        />
        {captions && captions.cps_warnings.length > 0 && (
          <ul className="flex flex-col gap-1 text-xs text-attention" aria-label="Lesetempo-Warnungen">
            {captions.cps_warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
        {!captions && <p className="text-xs text-text-2">Caption-Karten entstehen beim Render. Bis dahin zeigt die Vorschau nur Hook und Titelkarte.</p>}
      </GlassCard>
    </div>
  );
}
