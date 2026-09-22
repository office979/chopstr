import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { requirePageRole } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { buildHistory } from "@/lib/brand/history";
import { BrandForm } from "./BrandForm";
import { HistoryCard } from "./HistoryCard";

export const dynamic = "force-dynamic";
export const metadata = { title: "Markenprofil" };

export default async function BrandPage() {
  const session = await requirePageRole("brand.edit");
  const repo = getRepo();
  const profiles = await repo.listBrandProfiles();
  const profile = profiles[0] ?? null;
  const [assets, versions] = profile ? await Promise.all([repo.listBrandAssets(profile.id), repo.listBrandProfileVersions(profile.id)]) : [[], []];
  const history = profile ? buildHistory(versions, profile) : [];

  return (
    <PageShell width="narrow" backgroundWord="Marke">
      <PageHeader
        eyebrow="Brand Brain"
        title="Markenprofil"
        description="Anrede, Land und Wörterbuch steuern Transkription, Captions und später die Hooks. Alles bleibt in deinem Workspace."
      />
      <BrandForm profile={profile} assets={assets} canUploadAssets={can(session.role, "brand.assets")} />
      {profile && (
        <div className="mt-5">
          <HistoryCard profileId={profile.id} entries={history} canRestore={can(session.role, "brand.edit")} />
        </div>
      )}
    </PageShell>
  );
}
