import { PageShell } from "@/components/layout/PageShell";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { mediaUrl } from "@/lib/clips/labels";
import { Bibliothek, type ProjektZeile } from "./Bibliothek";

export const dynamic = "force-dynamic";

export const metadata = { title: "Meine Videos" };

export default async function ProjectsPage() {
  const session = await requireSession();
  const canDelete = can(session.role, "source.delete");
  const canUpload = can(session.role, "source.upload");
  const repo = getRepo();
  const sources = await repo.listSources();
  const clipCounts = new Map(
    await Promise.all(sources.filter((s) => s.status === "ready").map(async (s) => [s.id, await repo.countClips(s.id)] as const)),
  );

  /* Name der Marke je Projekt: in der Bibliothek ist das der Kunde, und danach wird auch gesucht.
   * Einmal geladen und zugeordnet, statt je Zeile eine Abfrage.
   *
   * Nur die Marken, die an einem sichtbaren Projekt hängen. Ein Nutzer, der auf eine Marke
   * eingeschränkt ist (session.brandScope), sieht ohnehin nur deren Projekte; so kommt aber auch
   * kein fremder Markenname bis in die Seite. */
  const gebrauchteMarken = new Set(sources.map((s) => s.brand_profile_id).filter(Boolean));
  const marken = new Map(
    (await repo.listBrandProfiles()).filter((b) => gebrauchteMarken.has(b.id)).map((b) => [b.id, b.name]),
  );

  /* Ein Vorschaubild je Projekt: das Poster des ersten gebauten Clips. Gibt es keins, bleibt die
   * Fläche leer - ein erfundenes Bild wäre schlimmer als keins. */
  const mediaBase = process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? null;
  const bilder = new Map(
    await Promise.all(
      sources
        .filter((s) => (clipCounts.get(s.id)?.rendered ?? 0) > 0)
        .map(async (s) => {
          const clips = await repo.listClips(s.id);
          const mit = clips.find((c) => c.poster_key);
          return [s.id, mediaUrl(mediaBase, mit?.poster_key ?? null)] as const;
        }),
    ),
  );

  const zeilen: ProjektZeile[] = sources.map((s) => ({
    source: s,
    clips: clipCounts.get(s.id) ?? null,
    marke: s.brand_profile_id ? (marken.get(s.brand_profile_id) ?? null) : null,
    bildSrc: bilder.get(s.id) ?? null,
    /* Kein Freigabestand mehr in der Liste: Clips entstehen fertig. */
    stand: null,
  }));

  return (
    <PageShell width="wide">
      <section className="relative mb-8 overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(135deg,rgba(2,12,245,0.42)_0%,rgba(20,34,255,0.22)_45%,rgba(27,26,98,0.35)_100%)] p-6 sm:p-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand/25 blur-3xl" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-[var(--tracking-display)] text-white sm:text-4xl">Meine Videos</h1>
          </div>
          {/* Der Weg zum Hochladen gehört auf die Seite selbst. In der Seitenleiste liegt er auf dem
           * Handy hinter dem Menü und ist damit unsichtbar. */}
          {canUpload && <ButtonLink href="/upload">Neues Video</ButtonLink>}
        </div>
      </section>

      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-medium">Alle Videos</h2>
        <span className="text-sm text-text-3">
          {sources.length} {sources.length === 1 ? "Video" : "Videos"}
        </span>
      </div>

      <Bibliothek zeilen={zeilen} canDelete={canDelete} canUpload={canUpload} />

    </PageShell>
  );
}

/* Eine Zahl mit dem Weg zu der Liste, die sie zählt. Ohne Ziel bleibt sie eine Zahl zum
 * Anschauen, und dann kann man sie auch weglassen. */
