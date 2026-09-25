import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { CADENCE_LABELS, calendarSlots } from "@/lib/series/variation";
import { PLATFORM_LABELS, patternLabel } from "@/lib/clips/labels";
import { STRUCTURE_LABELS } from "@/lib/candidates/labels";
import { formatDate } from "@/lib/format";
import { pruefstand } from "@/lib/clips/pruefstand";
import { SerieClips, type SerienClip } from "./SerieClips";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props) {
  const { id } = await params;
  const series = await getPublishingRepo().getSeries(id);
  return { title: series ? `Serie · ${series.name}` : "Serie" };
}

/* Serie: Regeln, Kalender (8 Slots zurück, 8 voraus, Lücken orange), zugeordnete Clips */
export default async function SeriesDetailPage({ params }: Props) {
  const { id } = await params;
  await requirePublishingPage("series.manage");
  const pub = getPublishingRepo();
  const series = await pub.getSeries(id);
  if (!series) notFound();
  const clips = await pub.listSeriesClips(id);
  const repo = getRepo();
  const sources = new Map<string, string>();
  await Promise.all([...new Set(clips.map((c) => c.source_id))].map(async (sid) => sources.set(sid, (await repo.getSource(sid))?.title ?? "Projekt")));
  const slots = calendarSlots(series, clips);
  const gaps = slots.filter((s) => s.gap).length;

  /* Der Zustand je Clip wie in der Clip-Übersicht, damit dieselbe Sache überall gleich heisst. */
  const zustandVon = (c: (typeof clips)[number]) => pruefstand({ clip: c, freigabe: null });

  const zeile = (c: (typeof clips)[number]): SerienClip => ({
    id: c.id,
    sourceId: c.source_id,
    projekt: sources.get(c.source_id) ?? "Projekt",
    plattform: c.platform,
    dauerS: c.duration_s,
    slot: c.series_index,
    geaendert: c.updated_at,
    stand: zustandVon(c),
  });

  const zeilen = clips.map(zeile);
  const zurWahl = await pub.listZuordenbareClips(series.id, 50);
  await Promise.all(
    [...new Set(zurWahl.map((c) => c.source_id))].map(async (sid) => {
      if (!sources.has(sid)) sources.set(sid, (await repo.getSource(sid))?.title ?? "Projekt");
    }),
  );
  const wahlZeilen = zurWahl.map(zeile);

  return (
    <PageShell width="default" backgroundWord="Serie">
      <PageHeader
        eyebrow="Serie"
        title={series.name}
        actions={
          <ButtonLink href="/serien" variant="ghost">
            Alle Serien
          </ButtonLink>
        }
        description={`${CADENCE_LABELS[series.cadence]} · ${series.brand_profile_name ?? "alle Marken"} · seit ${formatDate(series.created_at)}${series.description ? ` · ${series.description}` : ""}`}
      />

      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <GlassCard padding="lg">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-medium">Kalender</h2>
            <p className="text-xs text-text-2">{gaps === 0 ? "Keine Lücken in den letzten acht Slots." : `${gaps} ${gaps === 1 ? "Lücke" : "Lücken"} in den letzten acht Slots.`}</p>
          </div>
          {series.cadence === "none" ? (
            <p className="mt-3 text-sm text-text-2">Ohne Rhythmus gibt es keinen Kalender. Die Slots zählen wöchentlich, Lücken werden nicht markiert.</p>
          ) : null}
          <ol className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4" aria-label="Slots">
            {slots.map((s) => (
              <li
                key={s.index}
                className={cn(
                  "flex min-h-[72px] flex-col gap-1 rounded-inner border p-3 text-xs",
                  s.gap && series.cadence !== "none" ? "border-attention/60 bg-attention/10" : s.current ? "border-white/40 bg-white/5" : "border-line",
                )}
              >
                <span className={cn("font-mono tabular-nums", s.past ? "text-text-2" : "text-text")}>{formatDate(s.start)}</span>
                {s.clip_ids.length === 0 ? (
                  <span className={s.gap && series.cadence !== "none" ? "text-attention" : "text-text-3"}>{s.gap && series.cadence !== "none" ? "Lücke" : s.current ? "aktueller Slot" : "frei"}</span>
                ) : (
                  <span className="text-text">
                    {s.clip_ids.length} {s.clip_ids.length === 1 ? "Clip" : "Clips"}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </GlassCard>

        <GlassCard padding="lg">
          <h2 className="text-lg font-medium">Format dieser Serie</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-2">Aufbau</dt>
            <dd>{series.rules.structure ? STRUCTURE_LABELS[series.rules.structure] : "frei"}</dd>
            <dt className="text-text-2">Plattformen</dt>
            <dd>{(series.rules.platforms ?? []).map((p) => PLATFORM_LABELS[p]).join(", ") || "alle"}</dd>
            <dt className="text-text-2">Untertitel</dt>
            <dd>{series.rules.caption_preset ? (PRESET_NAME[series.rules.caption_preset] ?? series.rules.caption_preset) : "nach Plattform"}</dd>
            <dt className="text-text-2">Einstieg</dt>
            <dd>{(series.rules.hook_patterns ?? []).map((p) => patternLabel(p)).join(", ") || "frei"}</dd>
          </dl>
          {/* Was eine Änderung bewirkt, bevor jemand sie macht. Die Antwort ist hier angenehm
            * klar: die Regeln steuern den Kalender und den Ähnlichkeitsvergleich, sonst nichts.
            * Ein fertiger Clip ändert sich davon nicht - auch nicht heimlich. */}
          <p className="mt-4 text-sm text-text-2">
            Diese Angaben ändern nichts an fertigen Clips. Sie sagen nur, was in diese Serie passt:
            Der Ähnlichkeitsvergleich nimmt sie als Maßstab, wenn du einen Clip hinzufügst.
          </p>
        </GlassCard>
      </div>

      <SerieClips
        serieId={series.id}
        serieName={series.name}
        zugeordnet={zeilen}
        zurWahl={wahlZeilen}
        canEdit
      />

    </PageShell>
  );
}

/* Verständliche Namen für die Untertitel-Vorlagen. Spiegel der Liste in SeriesPanel und im
 * Clip-Editor: dieselbe Sache soll überall gleich heissen. */
const PRESET_NAME: Record<string, string> = {
  tiktok_words: "Ein Wort nach dem anderen, sehr groß",
  reels_words: "Ein Wort nach dem anderen, groß",
  shorts_words: "Ein Wort nach dem anderen, groß",
  tiktok_bold: "Zwei Zeilen, fett mit Rand",
  reels_clean: "Zwei Zeilen, schlicht",
  shorts_clean: "Zwei Zeilen, schlicht",
  linkedin_static: "Zwei Zeilen, ruhig auf Fläche",
  corporate_third: "Bauchbinde unten, ruhig und klein",
};
