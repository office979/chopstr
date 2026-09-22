"use client";

import Link from "next/link";
import { useCallback, useId, useState } from "react";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select, Textarea, Checkbox } from "@/components/ui/Field";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import type { HookPattern, Platform } from "@/lib/repo/types";
import type { Series, SeriesCadence } from "@/lib/repo/types-publishing";
import { PATTERN_LABELS, PATTERN_ORDER, PLATFORMS, PLATFORM_LABELS } from "@/lib/clips/labels";
import { STRUCTURE_LABELS } from "@/lib/candidates/labels";
import { PRESETS } from "@/lib/clips/presets";
import { CADENCE_LABELS } from "@/lib/series/variation";
import { CADENCES } from "@/lib/series/input";

interface Props {
  initialSeries: Series[];
  brands: { id: string; name: string }[];
}

interface ApiError {
  error?: string;
}

export function SeriesPanel({ initialSeries, brands }: Props) {
  const [series, setSeries] = useState(initialSeries);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [brand, setBrand] = useState("");
  const [cadence, setCadence] = useState<SeriesCadence>("weekly");
  const [structure, setStructure] = useState("");
  const [preset, setPreset] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>([...PLATFORMS]);
  const [patterns, setPatterns] = useState<HookPattern[]>([]);
  const ids = { name: useId(), desc: useId(), brand: useId(), cadence: useId(), structure: useId(), preset: useId() };

  const create = useCallback(async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await fetch("/api/series", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          description,
          brand_profile_id: brand || null,
          cadence,
          rules: { structure: structure || null, caption_preset: preset || null, platforms, hook_patterns: patterns },
        }),
      });
      const data = (await res.json()) as ApiError & { series?: Series };
      if (!res.ok || !data.series) throw new Error(data.error ?? "Anlegen fehlgeschlagen");
      setSeries((prev) => [data.series!, ...prev]);
      setOpen(false);
      setName("");
      setDescription("");
      setMessage({ tone: "ok", text: `Serie „${data.series.name}“ angelegt.` });
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Anlegen fehlgeschlagen" });
    } finally {
      setBusy(false);
    }
  }, [name, description, brand, cadence, structure, preset, platforms, patterns]);

  const toggleActive = useCallback(async (s: Series) => {
    try {
      const res = await fetch(`/api/series/${s.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ active: !s.active }) });
      const data = (await res.json()) as ApiError & { series?: Series };
      if (!res.ok || !data.series) throw new Error(data.error ?? "Speichern fehlgeschlagen");
      setSeries((prev) => prev.map((x) => (x.id === s.id ? data.series! : x)));
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Speichern fehlgeschlagen" });
    }
  }, []);

  return (
    <div className="flex flex-col gap-5">
      <Modal open={open} onClose={() => !busy && setOpen(false)} title="Serie anlegen" description="Name, Marke, Kadenz und Regeln. Die Regeln dienen der Variations-Prüfung und dem Kalender." className="max-w-[720px]">
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault();
            void create();
          }}
        >
          <Field label="Name" htmlFor={ids.name} required>
            <Input id={ids.name} value={name} onChange={(e) => setName(e.target.value)} maxLength={120} required />
          </Field>
          <Field label="Beschreibung" htmlFor={ids.desc}>
            <Textarea id={ids.desc} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={1000} className="min-h-20" />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Marke" htmlFor={ids.brand}>
              <Select id={ids.brand} value={brand} onChange={(e) => setBrand(e.target.value)}>
                <option value="">Alle Marken</option>
                {brands.map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Kadenz" htmlFor={ids.cadence}>
              <Select id={ids.cadence} value={cadence} onChange={(e) => setCadence(e.target.value as SeriesCadence)}>
                {CADENCES.map((c) => (
                  <option key={c} value={c}>
                    {CADENCE_LABELS[c]}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Struktur" htmlFor={ids.structure} hint="Regel für die Variations-Prüfung.">
              <Select id={ids.structure} value={structure} onChange={(e) => setStructure(e.target.value)}>
                <option value="">Frei</option>
                {Object.entries(STRUCTURE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Caption-Preset" htmlFor={ids.preset}>
              <Select id={ids.preset} value={preset} onChange={(e) => setPreset(e.target.value)}>
                <option value="">Nach Plattform</option>
                {Object.keys(PRESETS).map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium">Plattformen</legend>
            <div className="flex flex-wrap gap-3">
              {PLATFORMS.map((p) => (
                <label key={p} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={platforms.includes(p)} onChange={(e) => setPlatforms((cur) => (e.target.checked ? [...cur, p] : cur.filter((x) => x !== p)))} />
                  {PLATFORM_LABELS[p]}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium">Hook-Muster</legend>
            <div className="flex flex-wrap gap-3">
              {PATTERN_ORDER.map((p) => (
                <label key={p} className="flex items-center gap-2 text-sm">
                  <Checkbox checked={patterns.includes(p)} onChange={(e) => setPatterns((cur) => (e.target.checked ? [...cur, p] : cur.filter((x) => x !== p)))} />
                  {PATTERN_LABELS[p]}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="flex flex-wrap justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={busy}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={busy || name.trim().length < 2}>
              {busy ? "Wird angelegt" : "Anlegen"}
            </Button>
          </div>
        </form>
      </Modal>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-text-2">{series.length === 0 ? "Noch keine Serie." : `${series.length} ${series.length === 1 ? "Serie" : "Serien"}.`}</p>
        <Button size="sm" onClick={() => setOpen(true)}>
          Serie anlegen
        </Button>
      </div>
      {message && (
        <p role="status" aria-live="polite" className={cn("rounded-inner border px-4 py-3 text-sm", message.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text")}>
          {message.text}
        </p>
      )}
      {series.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch keine Serie</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">Lege ein wiederkehrendes Format an und ordne Clips über die Clip-Karte („Serie zuordnen“) zu.</p>
        </GlassCard>
      ) : (
        <ul className="grid gap-3 md:grid-cols-2">
          {series.map((s) => (
            <li key={s.id}>
              <GlassCard padding="md" className={cn("flex h-full flex-col gap-3", !s.active && "opacity-70")}>
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <Link href={`/serien/${s.id}`} className="text-base font-medium hover:underline">
                      {s.name}
                    </Link>
                    <p className="mt-0.5 text-xs text-text-2">
                      {CADENCE_LABELS[s.cadence]} · {s.brand_profile_name ?? "alle Marken"} · {s.clip_count ?? 0} Clips
                    </p>
                  </div>
                  <Badge tone={s.active ? "ok" : "neutral"} className="h-6 px-2.5 text-[11px]">
                    {s.active ? "aktiv" : "pausiert"}
                  </Badge>
                </div>
                {s.description && <p className="line-clamp-2 text-sm text-text-2">{s.description}</p>}
                <div className="flex flex-wrap gap-1.5 text-[11px]">
                  {s.rules.structure && <Badge className="h-6 px-2.5 text-[11px]">{STRUCTURE_LABELS[s.rules.structure]}</Badge>}
                  {s.rules.caption_preset && <Badge className="h-6 px-2.5 font-mono text-[11px]">{s.rules.caption_preset}</Badge>}
                  {(s.rules.platforms ?? []).map((p) => (
                    <Badge key={p} className="h-6 px-2.5 text-[11px]">
                      {PLATFORM_LABELS[p]}
                    </Badge>
                  ))}
                </div>
                <div className="mt-auto flex flex-wrap gap-2 border-t border-line pt-3">
                  <Link href={`/serien/${s.id}`} className="transition-soft inline-flex h-9 items-center rounded-pill bg-text px-4 text-sm font-medium text-black hover:bg-white">
                    Kalender
                  </Link>
                  <Button size="sm" variant="ghost" onClick={() => toggleActive(s)}>
                    {s.active ? "Pausieren" : "Aktivieren"}
                  </Button>
                </div>
              </GlassCard>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
