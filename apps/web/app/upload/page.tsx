import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { isDemoMode, uploadMaxBytes } from "@/lib/env";
import { requirePageRole } from "@/lib/session";
import { UploadForm } from "./UploadForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Upload" };

export default async function UploadPage() {
  await requirePageRole("source.upload");
  const repo = getRepo();
  const profiles = await repo.listBrandProfiles();

  return (
    <PageShell width="narrow" backgroundWord="Upload">
      <PageHeader
        eyebrow="Neues Projekt"
        title="Upload"
        description="Podcast, Keynote oder Interview als Video. Der Upload ist fortsetzbar, die Verarbeitung läuft in der EU."
      />
      <UploadForm
        profiles={profiles.map((p) => ({ id: p.id, name: p.name, platform: p.default_platform }))}
        maxBytes={uploadMaxBytes()}
        tusEndpoint={process.env.NEXT_PUBLIC_TUS_ENDPOINT ?? process.env.TUS_ENDPOINT ?? "http://localhost:1080/files/"}
        demoUpload={isDemoMode() || process.env.NEXT_PUBLIC_DEMO_UPLOAD === "true"}
      />
    </PageShell>
  );
}
