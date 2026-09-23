import Link from "next/link";
import { notFound } from "next/navigation";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { ButtonLink } from "@/components/ui/Button";
import { cn } from "@/components/ui/cn";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { CADENCE_LABELS, calendarSlots } from "@/lib/series/variation";
import { CLIP_STATUS_LABELS, PLATFORM_LABELS, formatClipDuration, patternLabel } from "@/lib/clips/labels";
import { STRUCTURE_LABELS } from "@/lib/candidates/labels";
import { formatDate, formatDateTime } from "@/lib/format";

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
  const hooks = await Promise.all(clips.map((c) => repo.getCurrentHook(c.id)));
  const sources = new Map<string, string>();
  await Promise.all([...new Set(clips.map((c) => c.source_id))].map(async (sid) => sources.set(sid, (await repo.getSource(sid))?.title ?? "Projekt")));
  const slots = calendarSlots(series, clips);
  const gaps = slots.filter((s) => s.gap).length;

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
          <h2 className="text-lg font-medium">Regeln</h2>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-2">Struktur</dt>
            <dd>{series.rules.structure ? STRUCTURE_LABELS[series.rules.structure] : "frei"}</dd>
            <dt className="text-text-2">Plattformen</dt>
            <dd>{(series.rules.platforms ?? []).map((p) => PLATFORM_LABELS[p]).join(", ") || "alle"}</dd>
            <dt className="text-text-2">Caption-Preset</dt>
            <dd className="font-mono">{series.rules.caption_preset ?? "nach Plattform"}</dd>
            <dt className="text-text-2">Hook-Muster</dt>
            <dd>{(series.rules.hook_patterns ?? []).map((p) => patternLabel(p)).join(", ") || "frei"}</dd>
          </dl>
          <p className="mt-4 text-xs text-text-2">Clips ordnest du auf der Clip-Karte zu („Serie zuordnen“). Die Variations-Prüfung vergleicht Caption-Preset, Hook-Muster, Struktur und Länge (±15 %) mit den letzten neun Clips.</p>
        </GlassCard>
      </div>

      <GlassCard padding="lg" className="mt-5">
        <h2 className="text-lg font-medium">Clips der Serie</h2>
        {clips.length === 0 ? (
          <p className="mt-2 text-sm text-text-2">Noch kein Clip zugeordnet.</p>
        ) : (
          <ul className="mt-3 flex flex-col gap-2">
            {clips.map((c, i) => (
              <li key={c.id} className="flex flex-wrap items-center justify-between gap-2 rounded-inner border border-line px-4 py-3 text-sm">
                <div className="min-w-0">
                  <Link href={`/projekte/${c.source_id}/clips`} className="font-medium hover:underline">
                    {sources.get(c.source_id)} · {PLATFORM_LABELS[c.platform]}
                  </Link>
                  <p className="mt-0.5 text-xs text-text-2">
                    Slot {c.series_index ?? "?"} · {patternLabel(hooks[i]?.pattern)} · {formatClipDuration(c.duration_s)} · {formatDateTime(c.updated_at)}
                  </p>
                </div>
                <Badge tone={c.status === "rendered" || c.status === "exported" ? "ok" : "neutral"} className="h-6 px-2.5 text-[11px]">
                  {CLIP_STATUS_LABELS[c.status]}
                </Badge>
              </li>
            ))}
          </ul>
        )}
      </GlassCard>
    </PageShell>
  );
}
