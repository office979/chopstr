import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { getRepo } from "@/lib/repo";
import { requirePageRole } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { buildHistory } from "@/lib/brand/history";
import { previewFontFor } from "@/lib/brand/preview-font";
import { fassungFuerVideo } from "@/lib/brand/fassung";
import { BrandForm } from "./BrandForm";
import { BrandList } from "./BrandList";
import { HistoryCard } from "./HistoryCard";

export const dynamic = "force-dynamic";
export const metadata = { title: "Marken" };

type Props = { searchParams: Promise<{ p?: string }> };

/* Mehrere Brandings je Workspace. Welches bearbeitet wird, steht in ?p=<id>; ?p=neu zeigt ein
 * leeres Formular. Ohne Parameter gilt das erste. Der Zustand steckt in der Adresse, damit ein
 * Neuladen nicht zurückspringt. */
export default async function BrandPage({ searchParams }: Props) {
  const session = await requirePageRole("brand.edit");
  const { p } = await searchParams;
  const repo = getRepo();
  const profiles = await repo.listBrandProfiles();

  const isNew = p === "neu";
  const profile = isNew ? null : (profiles.find((x) => x.id === p) ?? profiles[0] ?? null);
  const [assets, versions] = profile
    ? await Promise.all([repo.listBrandAssets(profile.id), repo.listBrandProfileVersions(profile.id)])
    : [[], []];
  const history = profile ? buildHistory(versions, profile) : [];
  /* Die Marken-Schrift für die Beispielszene: sie ist an dieses Profil gebunden (die Prüfung
   * steckt in previewFontFor), damit sich zwei Kundenprofile nicht ins Gehege kommen. */
  const vorschauSchrift = profile ? await previewFontFor(repo, profile) : null;
  /* Wie viele Projekte dieses Profil schon benutzt haben. Daran hängt der Satz darüber, was eine
   * Änderung bewirkt: gebaute Clips behalten ihr Aussehen. */
  /* Die Videos dieser Marke, jeweils mit der Fassung, mit der sie geclippt wurden.
   *
   * Das ist die Frage vor jeder Markenänderung: welche Videos betrifft das, und welche zeigen
   * noch die alte Fassung? Vorher stand hier nur eine Zahl, und die beantwortet sie nicht. */
  const betroffen = profile
    ? await (async () => {
        const quellen = (await repo.listSources()).filter((s) => s.brand_profile_id === profile.id);
        const staende = await repo.listClipStands();
        return quellen.map((s) => {
          /* Nur fertig geclippte Clips. Einer, der gerade läuft, hat noch keinen Plan und damit
             * keine Fassung - er zählt nicht als „nicht vermerkt", sondern gar nicht. */
          const fassungen = staende
            .filter((c) => c.source_id === s.id && (c.status === "rendered" || c.status === "exported"))
            .map((c) => c.marken_fassung);
          return { id: s.id, titel: s.title, fassung: fassungFuerVideo(fassungen, profile.version) };
        });
      })()
    : [];

  return (
    <PageShell backgroundWord="Marke">
      {/* „Marke" durchgehend: so heisst der Punkt in der Navigation, so steht es im Pfad auf den
          Clipseiten, und so heisst die Sache auch beim Kunden. „Aussehen" war ein vierter Name
          für dasselbe. */}
      <PageHeader
        eyebrow="Ein Profil je Kunde"
        title="Marken"
        description="Farben, Logo, Schrift und Schreibweisen. Sie bestimmen, wie die Clips einer Marke aussehen und klingen. Alles bleibt in deinem Team."
      />
      <BrandList profiles={profiles} activeId={profile?.id ?? null} isNew={isNew} />
      {/* key erzwingt ein frisches Formular beim Wechsel; sonst blieben die Eingaben des vorigen stehen */}
      <BrandForm
        key={isNew ? "neu" : (profile?.id ?? "leer")}
        profile={profile}
        assets={assets}
        canUploadAssets={can(session.role, "brand.assets")}
        vorschauSchrift={vorschauSchrift}
        betroffeneVideos={betroffen}
      />
      {profile && !isNew && (
        <div className="mt-5">
          <HistoryCard profileId={profile.id} entries={history} canRestore={can(session.role, "brand.edit")} />
        </div>
      )}
    </PageShell>
  );
}
