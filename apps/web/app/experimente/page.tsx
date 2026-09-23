import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { formatDateTime } from "@/lib/format";
import { PLATFORM_LABELS } from "@/lib/clips/labels";

export const dynamic = "force-dynamic";
export const metadata = { title: "Experimente" };

const STATUS = { draft: "Entwurf", running: "Läuft", decided: "Entschieden" } as const;

/* Hook-A/B-Experimente: Liste mit Status, Varianten und Konfidenz */
export default async function ExperimentsPage() {
  const session = await requirePublishingPage("experiments.manage");
  const pub = getPublishingRepo();
  const experiments = await pub.listExperiments();
  const clipsByExperiment = new Map<string, Awaited<ReturnType<typeof pub.listClipsForExperiment>>>();
  await Promise.all(experiments.map(async (e) => clipsByExperiment.set(e.id, await pub.listClipsForExperiment(e.id))));

  return (
    <PageShell width="default" backgroundWord="A/B">
      <PageHeader eyebrow={`Workspace · ${session.workspaceName}`} title="Experimente" description="Zwei Hooks, gleiche Komposition. Entscheidung erst nach 48 Stunden und Mindestexposure, mit Konfidenz über die Folgequote." />
      {experiments.length === 0 ? (
        <GlassCard padding="lg" className="text-center">
          <p className="text-lg font-medium">Noch kein Experiment</p>
          <p className="mx-auto mt-2 max-w-md text-text-2">Im Hook-Studio eines gerenderten Clips legst du mit „Variante B anlegen“ ein Experiment an.</p>
        </GlassCard>
      ) : (
        <ul className="flex flex-col gap-3">
          {experiments.map((e) => {
            const clips = clipsByExperiment.get(e.id) ?? [];
            const a = clips.find((c) => c.variant === "A");
            return (
              <li key={e.id}>
                <Link href={`/experimente/${e.id}`} className="block">
                  <GlassCard padding="md" className="transition-soft hover:border-line-strong">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium">{e.hypothesis ?? "Ohne Hypothese"}</p>
                        <p className="mt-1 text-xs text-text-2">
                          {a ? PLATFORM_LABELS[a.platform] : "Plattform offen"} · {clips.length} von 2 Varianten · angelegt {formatDateTime(e.created_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {e.confidence != null && <span className="font-mono text-xs text-text-2">P(A&gt;B) {(e.confidence * 100).toFixed(0)} %</span>}
                        <Badge tone={e.status === "decided" ? "ok" : e.status === "running" ? "ai" : "neutral"}>{STATUS[e.status]}</Badge>
                      </div>
                    </div>
                  </GlassCard>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </PageShell>
  );
}
