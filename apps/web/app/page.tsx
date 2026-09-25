import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { mediaUrl } from "@/lib/clips/labels";
import { Bibliothek, type ProjektZeile } from "./Bibliothek";
import {
  FREIGABE_HINWEIS,
  FREIGABE_LABEL,
  freigabeAusZeile,
  standAusZeile,
  zaehlen,
  zaehlerFuer,
  type FreigabeStand,
} from "@/lib/clips/pruefstand";

export const dynamic = "force-dynamic";

export const metadata = { title: "Meine Videos" };

export default async function ProjectsPage() {
  const session = await requireSession();
  const canDelete = can(session.role, "source.delete");
  const canUpload = can(session.role, "source.upload");
  const repo = getRepo();
  const sources = await repo.listSources();
  /* Der Freigabestand aller Clips in einer Abfrage, gerechnet mit demselben Modell wie an der
   * Clip-Karte. Gezählt werden CLIPS, nicht Videos: jeder Clip wird einzeln freigegeben. */
  const zeilenStand = await repo.listClipStands();
  const staendeJeQuelle = new Map<string, FreigabeStand[]>();
  for (const r of zeilenStand) {
    const liste = staendeJeQuelle.get(r.source_id) ?? [];
    liste.push(freigabeAusZeile(r, standAusZeile(r)));
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

  /* Dieselben Zahlen über alle Videos zusammen: wie viele CLIPS in welchem Freigabestand stehen.
   * Nicht wie viele Videos - freigegeben wird je Clip. */
  const alle = zaehlen([...staendeJeQuelle.values()].flat());
  /* Wohin eine Kachel führt: zum ersten Video, das Clips in diesem Zustand hat. Ohne Ziel wäre
   * die Zahl nur zum Anschauen da. */
  const zielFuer = (f: FreigabeStand) => {
    const treffer = [...videoStaende.entries()].find(([, z]) => zaehlerFuer(z, f) > 0);
    return treffer ? `/projekte/${treffer[0]}/clips` : null;
  };

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
        {/* Zahlen erst, wenn es etwas zu zählen gibt. Fünf Nullen sind für jemanden, der gerade
         * anfängt, das grösste Element der Seite und sagen nichts.
         *
         * Gezählt werden CLIPS in ihrem Freigabestand - dieselben fünf Zustände wie an der
         * Clip-Karte. Vorher standen hier drei verschiedene Fragen nebeneinander („Fehler
         * beheben", „Wird geclippt", „Bereit zum Posten"), und keine davon war die, um die es
         * geht: darf das raus, und wer muss dafür noch etwas tun? */}
        {sources.length > 0 && alle.gesamt > 0 && (
          <dl className="relative mt-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
            {(["nicht_gesendet", "ausstehend", "fehlerhaft", "abgelehnt", "freigegeben"] as FreigabeStand[]).map((f) => (
              <Stat
                key={f}
                label={FREIGABE_LABEL[f]}
                value={zaehlerFuer(alle, f)}
                hint={FREIGABE_HINWEIS[f]}
                href={zielFuer(f)}
              />
            ))}
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
