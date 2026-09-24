import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { formatDateTime } from "@/lib/format";
import { ButtonLink } from "@/components/ui/Button";
import { PLATFORM_LABELS } from "@/lib/clips/labels";
import { getRepo } from "@/lib/repo";

export const dynamic = "force-dynamic";
export const metadata = { title: "Tests" };

/* Der Stand eines Tests in Worten, die auch ohne Statistikwissen tragen. „draft" heisst: die
 * zweite Fassung steht, aber noch ist nichts gepostet. */
const STATUS = { draft: "Noch nicht gepostet", running: "Läuft", decided: "Entschieden" } as const;

/* Hook-A/B-Experimente: Liste mit Status, Varianten und Konfidenz */
export default async function ExperimentsPage() {
  const session = await requirePublishingPage("experiments.manage");
  const pub = getPublishingRepo();
  const experiments = await pub.listExperiments();
  /* Für die Leerseite: irgendein fertig geclippter Clip, an dem sich ein Test anlegen lässt. Ohne
   * ihn wäre der Knopf eine Sackgasse, und dann steht dort auch kein Knopf. */
  const ersterClip = experiments.length === 0 ? await ersterFertigerClip() : null;
  const clipsByExperiment = new Map<string, Awaited<ReturnType<typeof pub.listClipsForExperiment>>>();
  await Promise.all(experiments.map(async (e) => clipsByExperiment.set(e.id, await pub.listClipsForExperiment(e.id))));

  return (
    <PageShell width="default" backgroundWord="A/B">
      {/* „Tests" heisst es in der Navigation, also heisst es hier auch so. Vorher standen zwei
          Namen für dieselbe Sache nebeneinander.
          Die Beschreibung war Fachsprache: „Hooks", „Komposition", „Mindestexposure",
          „Konfidenz", „Folgequote". Davon versteht ein Creator kein Wort, und er müsste es auch
          nicht - was hier passiert, lässt sich in zwei Sätzen sagen. */}
      <PageHeader
        eyebrow={`Team · ${session.workspaceName}`}
        title="Tests"
        description="Derselbe Clip, zwei verschiedene Einstiege. Du postest beide und siehst nach ein paar Tagen, welcher besser ankommt. Entschieden wird erst, wenn genug Zahlen da sind."
      />
      {experiments.length === 0 ? (
        /* Eine Leerseite, die den Weg nennt UND ihn anbietet. Vorher stand hier ein Satz über das
           „Hook-Studio eines gerenderten Clips" - ohne Link, ohne Erklärung, was ein Hook-Studio
           ist, und ohne zu sagen, welcher Clip dafür taugt. */
        <GlassCard padding="lg" className="flex flex-col items-center gap-4 text-center">
          <div>
            <p className="text-lg font-medium">Noch kein Test</p>
            <p className="mx-auto mt-2 max-w-lg text-text-2">
              {'Ein Test vergleicht zwei Einstiege desselben Clips. Du brauchst dafür einen Clip, der schon fertig geclippt ist: dort legst du unter „Einstieg“ eine zweite Fassung an, postest beide und trägst später die Zahlen ein.'}
            </p>
          </div>
          {ersterClip ? (
            <ButtonLink href={`/projekte/${ersterClip.source_id}/clips/${ersterClip.id}/hooks`}>
              Ersten Einstieg vergleichen
            </ButtonLink>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <p className="text-sm text-text-3">Dafür fehlt noch ein fertig geclipptes Video.</p>
              <ButtonLink href="/" variant="ghost">
                Zu meinen Videos
              </ButtonLink>
            </div>
          )}
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
                          {a ? PLATFORM_LABELS[a.platform] : "Plattform offen"} · {clips.length} von 2 Fassungen · angelegt {formatDateTime(e.created_at)}
                        </p>
                      </div>
                      <div className="flex items-center gap-2">
                        {/* „P(A>B) 73 %" ist Notation aus einem Statistikbuch. Gemeint ist: wie
                            sicher ist es, dass die erste Fassung wirklich besser ist. */}
                        {e.confidence != null && (
                          <span className="text-xs text-text-2">
                            {(e.confidence * 100).toFixed(0)} % sicher für Fassung A
                          </span>
                        )}
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

/* Der erste fertig geclippte Clip des Teams. Gebraucht für den Knopf auf der Leerseite: ein Test
 * setzt einen Clip voraus, der schon existiert. Ohne einen solchen Clip führt der Knopf ins
 * Leere, und dann gehört er auch nicht dorthin. */
async function ersterFertigerClip(): Promise<{ id: string; source_id: string } | null> {
  const repo = getRepo();
  for (const s of await repo.listSources()) {
    if (s.status !== "ready") continue;
    const clip = (await repo.listClips(s.id)).find((c) => c.status === "rendered" || c.status === "exported");
    if (clip) return { id: clip.id, source_id: clip.source_id };
  }
  return null;
}
