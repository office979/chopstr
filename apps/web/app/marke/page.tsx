import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { BrandForm } from "./BrandForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Markenprofil" };

export default async function BrandPage() {
  const repo = getRepo();
  const profiles = await repo.listBrandProfiles();
  const profile = profiles[0] ?? null;

  return (
    <PageShell width="narrow" backgroundWord="Marke">
      <PageHeader
        eyebrow="Brand Brain"
        title="Markenprofil"
        description="Anrede, Land und Wörterbuch steuern Transkription, Captions und später die Hooks. Alles bleibt in deinem Workspace."
      />
      <BrandForm profile={profile} />
    </PageShell>
  );
}
