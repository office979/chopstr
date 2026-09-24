import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { SeriesPanel } from "./SeriesPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Serien" };

/* Content-Serien (editor, admin, owner): Liste und Anlegen. Kalender und Zuordnung auf der Detailseite. */
export default async function SeriesPage() {
  const session = await requirePublishingPage("series.manage");
  const [series, brands] = await Promise.all([getPublishingRepo().listSeries(), getRepo().listBrandProfiles()]);
  return (
    <PageShell width="default" backgroundWord="Serie">
      <PageHeader eyebrow={`Team · ${session.workspaceName}`} title="Serien" description="Wiederkehrende Formate für deine Clips. Wenn ein neuer Clip den letzten sehr ähnelt, sagt chopstr Bescheid." />
      <SeriesPanel initialSeries={series} brands={brands.map((b) => ({ id: b.id, name: b.name }))} />
    </PageShell>
  );
}
