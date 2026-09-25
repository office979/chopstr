import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { mediaUrl } from "@/lib/clips/labels";
import { Bibliothek, type ProjektZeile } from "./Bibliothek";
import { projektZustand } from "@/lib/projekte/projekt-zustand";
import { naechsteAufgabe, standAusZeile, zaehlen, type Pruefstand } from "@/lib/clips/pruefstand";

export const dynamic = "force-dynamic";

export const metadata = { title: "Meine Videos" };

export default async function ProjectsPage() {
  const session = await requireSession();
  const canDelete = can(session.role, "source.delete");
  const canUpload = can(session.role, "source.upload");
  const repo = getRepo();
  const sources = await repo.listSources();
  /* Der Stand aller Clips in einer Abfrage, gerechnet mit demselben Modell wie auf der
   * Prüfseite. Vorher zählte diese Seite selbst, und zwar schwächer: zwei verschiedene Namen
   * standen beide auf vierzehn - über denselben vierzehn Clips, von denen keiner freigegeben
   * war. */
  const zeilenStand = await repo.listClipStands();
  const staendeJeQuelle = new Map<string, Pruefstand[]>();
  for (const r of zeilenStand) {
    const liste = staendeJeQuelle.get(r.source_id) ?? [];
    liste.push(standAusZeile(r));
    staendeJeQuelle.set(r.source_id, liste);
  }
  const videoStaende = new Map(
    sources.map((s) => [s.id, zaehlen(staendeJeQuelle.get(s.id) ?? [])] as const),
  );
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
    stand: videoStaende.get(s.id) ?? null,
  }));

  /* Vertragshinweis nur hier und am Clip, nicht mehr über jeder Seite (Bedienkonzept, Abschnitt 7) */
  let dpaMissing = false;
  if (can(session.role, "dpa.accept")) {
    try {
      dpaMissing = !(await repo.getWorkspace()).dpa_signed_at;
    } catch {
      /* ohne Workspace kein Hinweis */
    }
  }

  const failedCount = sources.filter((s) => s.status === "failed").length;
  /* Die Zahlen über alle Videos, aus denselben Ständen. */
  const gesamt = [...videoStaende.values()].reduce(
    (a, z) => ({
      fehler: a.fehler + z.fehler,
      wirdGebaut: a.wirdGebaut + z.wirdGebaut,
      postbereit: a.postbereit + z.postbereit,
    }),
    { fehler: 0, wirdGebaut: 0, postbereit: 0 },
  );
  /* Das Video, bei dem die Arbeit anfängt: das dringendste zuerst. Ein Link auf „3 Clips prüfen"
   * ohne Ziel wäre eine Zahl zum Anschauen. */
  const dringend = [...videoStaende.entries()]
    .map(([id, z]) => ({ id, z, auf: naechsteAufgabe(z) }))
    .filter((x) => x.auf != null);
  const zielFuer = (art: "fehler" | "wird_erstellt" | "postbereit") => {
    const treffer = dringend.find((x) =>
      art === "fehler" ? x.z.fehler > 0 : art === "wird_erstellt" ? x.z.wirdGebaut > 0 : x.z.postbereit > 0,
    );
    return treffer ? `/projekte/${treffer.id}/clips#${art}` : null;
  };
  /* „In Arbeit" heisst hier dasselbe wie in der Liste: der Zustand aus projektZustand, damit
   * Kopfzahl und Karten nicht auseinanderlaufen. */
  const activeCount = zeilen.filter((z) => {
    const zu = projektZustand(z.source, z.clips);
    return zu === "verarbeitung" || zu === "upload";
  }).length;

  return (
    <PageShell width="wide">
      <section className="relative mb-8 overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(135deg,rgba(2,12,245,0.42)_0%,rgba(20,34,255,0.22)_45%,rgba(27,26,98,0.35)_100%)] p-6 sm:p-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-brand/25 blur-3xl" />
        <div className="relative flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-[var(--tracking-display)] text-white sm:text-4xl">Meine Videos</h1>
            <p className="mt-2 text-[15px] text-white/75">
              Hallo {session.displayName.split(/\s+/)[0]}. Langes Video rein, kurze Clips raus.
            </p>
          </div>
          {/* Der Weg zum Hochladen gehört auf die Seite selbst. In der Seitenleiste liegt er auf dem
           * Handy hinter dem Menü und ist damit unsichtbar. */}
          {canUpload && <ButtonLink href="/upload">Neues Video</ButtonLink>}
        </div>
        {/* Zahlen erst, wenn es etwas zu zählen gibt. Vier Nullen sind für jemanden, der gerade
         * anfängt, das größte Element der Seite und sagen nichts. */}
        {sources.length > 0 && (
          <dl className="relative mt-6 grid grid-cols-2 gap-3 lg:grid-cols-3">
            {/* Drei Zahlen, die verschiedene Dinge zählen und jede zu ihrer Arbeitsliste führt.
              * „Clips prüfen" und „Videos neu clippen" standen hier einmal daneben. Die erste war
              * nur die Zahl der noch nicht entschiedenen Clips, also am frischen Video gleich der
              * Gesamtzahl; die zweite kann es nicht mehr geben, seit Speichern sofort neu clippt. */}
            <Stat
              label="Fehler beheben"
              value={gesamt.fehler}
              hint={gesamt.fehler > 0 ? "hier stimmt der Inhalt nicht" : "nichts zu beheben"}
              href={zielFuer("fehler")}
            />
            <Stat
              label="Wird geclippt"
              value={gesamt.wirdGebaut}
              hint={gesamt.wirdGebaut > 0 ? "der Computer rechnet" : activeCount > 0 ? "erst wird das Video verarbeitet" : "gerade läuft nichts"}
              href={zielFuer("wird_erstellt")}
            />
            <Stat
              label="Bereit zum Posten"
              value={gesamt.postbereit}
              hint={failedCount > 0 ? `bei ${failedCount} ${failedCount === 1 ? "Video" : "Videos"} ging etwas schief` : "freigegeben und fertig geclippt"}
              href={zielFuer("postbereit")}
            />
          </dl>
        )}
      </section>

      {dpaMissing && (
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3 rounded-inner border border-attention/40 px-4 py-3 text-sm">
          <span className="text-text-2">
            <span className="text-attention">Ein Vertrag fehlt noch.</span> Hochladen und Clips bauen geht schon. Zum Posten
            brauchst du ihn.
          </span>
          <Link href="/rechtliches/avv" className="text-text underline-offset-4 hover:underline">
            Vertrag lesen und annehmen
          </Link>
        </div>
      )}

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
function Stat({ label, value, hint, href }: { label: string; value: number; hint: string; href?: string | null }) {
  const inhalt = (
    <>
      <dt className="text-sm text-text-2">{label}</dt>
      <dd className="mt-2 font-mono text-3xl font-medium tabular-nums text-text">{String(value).padStart(2, "0")}</dd>
      <dd className="mt-1 text-xs text-text-3">{hint}</dd>
    </>
  );
  if (href && value > 0) {
    return (
      <Link
        href={href}
        className="transition-soft block rounded-inner bg-black/45 p-4 backdrop-blur-sm hover:bg-black/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white/60 sm:p-5"
      >
        {inhalt}
      </Link>
    );
  }
  return (
    <div className="rounded-inner bg-black/45 p-4 backdrop-blur-sm sm:p-5">
      {inhalt}
    </div>
  );
}
