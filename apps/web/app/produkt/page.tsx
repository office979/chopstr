import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import { Wordmark } from "@/components/brand/Wordmark";
import { BlueBubbles } from "@/components/ui/BlueBubbles";
import { ProductMockup } from "@/components/landing/ProductMockup";

/* Öffentliche Landingpage. Aufbau nach Conversion-Leitfaden: schlanke Navigation, Hero mit Zielgruppe und einem Ziel
 * (kostenlos testen), Produktbild, Vertrauen, Problem, Lösung, drei Schritte, Belege, FAQ, Abschluss-CTA.
 * Bewusst ohne Preise, ohne Client-JavaScript und ohne Bilddateien, damit sie schnell lädt.
 * TODO: Kundenzitate ergänzen, sobald echte Freigaben aus dem Pilot vorliegen (keine erfundenen Stimmen). */

export const dynamic = "force-static";

export const metadata: Metadata = {
  title: "Clips aus langen Videos, die Sinn ergeben",
  description:
    "chopstr macht aus Podcasts, Interviews und Vorträgen auf Deutsch fertige Clips für TikTok, Reels, Shorts und LinkedIn. Sauber geschnitten, jede Auswahl erklärt, in der EU verarbeitet.",
  openGraph: {
    title: "chopstr · Clips aus langen Videos, die Sinn ergeben",
    description: "Aus einem langen Video werden fertige Clips für TikTok, Reels, Shorts und LinkedIn. Du gibst frei, bevor etwas online geht.",
    locale: "de_AT",
    type: "website",
  },
};

const SIGNUP = "/registrieren";

export default function LandingPage() {
  return (
    <div className="relative min-h-dvh overflow-x-clip">
      <BlueBubbles />

      {/* Navigation: Logo, drei Sprungmarken, Anmelden, eine Hauptaktion */}
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-black/50 backdrop-blur-xl">
        <nav aria-label="Seitennavigation" className="mx-auto flex h-16 max-w-[1200px] items-center gap-6 px-4 sm:px-8">
          <Link href="/produkt" aria-label="chopstr" className="shrink-0">
            <Wordmark width={96} />
          </Link>
          <ul className="hidden flex-1 items-center justify-center gap-8 text-sm text-text-2 md:flex">
            <li><a href="#so-gehts" className="transition-soft hover:text-text">So geht&apos;s</a></li>
            <li><a href="#funktionen" className="transition-soft hover:text-text">Funktionen</a></li>
            <li><a href="#teams" className="transition-soft hover:text-text">Für Teams</a></li>
            <li><a href="#fragen" className="transition-soft hover:text-text">Fragen</a></li>
          </ul>
          <div className="ml-auto flex items-center gap-2 md:ml-0">
            <Link href="/anmelden" className="transition-soft hidden h-10 items-center rounded-pill px-4 text-sm font-medium text-text-2 hover:text-text sm:flex">
              Anmelden
            </Link>
            <PrimaryCta size="sm">Kostenlos testen</PrimaryCta>
          </div>
        </nav>
      </header>

      <main className="relative z-10">
        {/* Hero */}
        <section className="mx-auto max-w-[1200px] px-4 pb-16 pt-16 text-center sm:px-8 sm:pt-24">
          <p className="mx-auto inline-flex items-center gap-2 rounded-md bg-white/[0.06] px-3 py-1.5 text-sm text-text-2">
            <span className="h-1.5 w-1.5 rounded-full bg-ai-soft" aria-hidden="true" />
            Für alle, die auf Deutsch reden und zu wenig Zeit zum Schneiden haben
          </p>
          <h1 className="mx-auto mt-6 max-w-[900px] text-4xl font-semibold leading-[1.05] tracking-[var(--tracking-display)] text-text sm:text-6xl lg:text-7xl">
            Aus einem langen Video werden Clips, die Sinn ergeben
          </h1>
          <p className="mx-auto mt-6 max-w-[640px] text-lg leading-relaxed text-text-2 sm:text-xl">
            chopstr sucht die Stellen, die für sich allein funktionieren, schneidet sie nie mitten im Gedanken ab und macht sie fertig für TikTok, Reels, Shorts und LinkedIn. Du schaust drüber und gibst frei.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <PrimaryCta>Kostenlos testen</PrimaryCta>
            <a
              href="#so-gehts"
              className="transition-soft inline-flex h-12 items-center rounded-pill border border-white/15 px-7 text-[15px] font-medium text-text hover:border-white/30 hover:bg-white/5"
            >
              So funktioniert&apos;s
            </a>
          </div>
          <ul className="mt-5 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm text-text-3">
            <Check>Ohne Kreditkarte</Check>
            <Check>Daten bleiben in der EU</Check>
            <Check>Nichts geht ohne dich online</Check>
          </ul>

          <div className="mt-16 sm:mt-20">
            <ProductMockup />
          </div>
        </section>

        {/* Vertrauensleiste: Plattformen statt Kundenlogos */}
        <section aria-label="Unterstützte Plattformen" className="border-y border-white/[0.06] bg-black/30">
          <div className="mx-auto flex max-w-[1200px] flex-col items-center gap-5 px-4 py-8 sm:flex-row sm:justify-between sm:px-8">
            <p className="text-sm text-text-3">Fertige Clips im richtigen Format für</p>
            <ul className="flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-lg font-semibold tracking-tight text-text-2">
              <li>TikTok</li>
              <li>Instagram Reels</li>
              <li>YouTube Shorts</li>
              <li>LinkedIn</li>
            </ul>
          </div>
        </section>

        {/* Problem */}
        <Section eyebrow="Das Problem" title="Clips schneiden frisst deinen Tag">
          <div className="grid gap-4 md:grid-cols-3">
            <ProblemCard title="Stundenlang suchen" text="Du scrollst durch eine ganze Folge, um die drei Minuten zu finden, die sich lohnen. Nächste Woche wieder." />
            <ProblemCard title="Mitten im Satz abgeschnitten" text="Automatische Tools schneiden, wo es gerade passt. Dann fehlt das „nicht“ und die Aussage ist plötzlich falsch." />
            <ProblemCard title="Untertitel voller Fehler" text="Namen, Fachwörter und Österreichisch werden verhunzt. Aus Jänner wird Januar, aus dem Firmennamen Kauderwelsch." />
          </div>
        </Section>

        {/* Lösung als Bento */}
        <Section id="funktionen" eyebrow="Die Lösung" title="Gute Clips, ohne dass du schneiden können musst">
          <div className="grid gap-4 md:grid-cols-6">
            <Feature className="md:col-span-4" title="Schneidet dort, wo der Gedanke fertig ist" text="chopstr versteht deutsche Sätze. Verneinungen, Nebensätze und Pointen bleiben drin. Kein Clip verdreht, was gesagt wurde.">
              <div className="mt-6 space-y-2 font-mono text-[13px]">
                <p className="rounded-md bg-white/[0.05] px-3 py-2 text-text-3 line-through decoration-danger/70">„Das funktioniert.“</p>
                <p className="rounded-md bg-ai/10 px-3 py-2 text-text">„Das funktioniert <span className="text-ai-soft">nicht</span>, solange niemand zuhört.“</p>
              </div>
            </Feature>
            <Feature className="md:col-span-2" title="Jede Auswahl erklärt" text="Zu jedem Clip steht, warum die Stelle trägt. Du entscheidest in Sekunden statt in Minuten." />
            <Feature className="md:col-span-2" title="Untertitel, die dich kennen" text="Trag Namen und Lieblingswörter einmal ein. Jänner bleibt Jänner, Marille bleibt Marille." />
            <Feature className="md:col-span-2" title="Automatisch im Hochformat" text="Das Gesicht bleibt im Bild, Folien werden eingeblendet. Fertig für jedes Handy." />
            <Feature className="md:col-span-2" title="Texte ohne KI-Blabla" text="Hook und Beitragstext klingen nach dir. Floskeln wie „Game Changer“ sperrst du einfach." />
          </div>
        </Section>

        {/* So geht's */}
        <Section id="so-gehts" eyebrow="So geht's" title="In drei Schritten zum fertigen Clip">
          <ol className="grid gap-4 md:grid-cols-3">
            <Step n={1} title="Video hochladen" text="Podcast, Interview oder Vortrag reinziehen. Bis 5 GB, der Upload läuft auch nach einer Pause weiter." />
            <Step n={2} title="Clips auswählen" text="chopstr zeigt dir die Vorschläge und schreibt dazu, warum die Stelle trägt. Du nimmst, was passt, oder ziehst den Anfang und das Ende zurecht." />
            <Step n={3} title="Clips herunterladen" text="Mit Untertiteln, Hook und Beitragstext. Fertig zum Posten auf TikTok, Reels, Shorts oder LinkedIn." />
          </ol>
          <div className="mt-10 flex justify-center">
            <PrimaryCta>Erstes Video kostenlos testen</PrimaryCta>
          </div>
        </Section>

        {/* Für Teams: zweite Tiefe. Oben spricht die Seite die Einzelperson an, hier kommen die
            Argumente, die erst zählen, wenn mehrere Leute und Kunden im Spiel sind. */}
        <Section id="teams" eyebrow="Für Teams" title="Wenn nicht nur du mitredest">
          <p className="mx-auto -mt-2 mb-8 max-w-[720px] text-center text-[17px] leading-relaxed text-text-2">
            Sobald Kolleginnen, Kunden oder eine Rechtsabteilung mitreden, wird aus Schneiden ein Prozess.
            chopstr kennt den Teil auch.
          </p>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Feature title="Freigabe per Link" text="Schick den Clip an die Kundin. Sie sieht ihn im Browser, sagt Ja oder wünscht Änderungen. Kein Konto, kein Download, kein Mailanhang." />
            <Feature title="Rollen statt Zugriff für alle" text="Wer hochladen darf, wer freigibt, wer nur zuschaut. Gäste sehen genau einen Clip und sonst nichts." />
            <Feature title="Ein eigenes Aussehen je Kunde" text="Farben, Logo, Schrift, Wörterbuch und Untertitel-Stil pro Marke. Wer für drei Kunden arbeitet, mischt sie nicht mehr." />
            <Feature title="Der Papierkram ist erledigt" text="Auftragsverarbeitungsvertrag, Subprozessoren und Löschnachweise liegen bereit. Jede Aktion steht im Protokoll." />
          </div>
        </Section>

        {/* Belege und Sicherheit */}
        <Section eyebrow="Warum chopstr" title="Gebaut für den DACH-Raum, nicht übersetzt">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Proof value="DE · AT · CH" label="Versteht Deutsch, Österreichisch und Schweizerdeutsch (Beta)" />
            <Proof value="EU" label="Verarbeitung und Speicherung nur in der EU, Auftragsverarbeitungsvertrag inklusive" />
            <Proof value="100 %" label="Freigabe durch dich. chopstr schlägt vor, veröffentlicht aber nie von allein" />
            <Proof value="-16 LUFS" label="Ton nach Sendestandard, jeder Clip gleich laut" />
          </div>
        </Section>

        {/* FAQ */}
        <Section id="fragen" eyebrow="Fragen" title="Was Leute vorher wissen wollen">
          <div className="mx-auto flex max-w-[820px] flex-col gap-3">
            <Faq q="Muss ich Videos schneiden können?">
              Nein. Du lädst das Video hoch und wählst aus den Vorschlägen. Schnitt, Hochformat, Untertitel und Ton macht chopstr.
            </Faq>
            <Faq q="Welche Videos funktionieren?">
              Alles, wo Menschen sprechen: Podcasts, Interviews, Vorträge, Webinare, Diskussionen. Video oder nur Audio, bis 5 GB pro Datei.
            </Faq>
            <Faq q="Postet chopstr automatisch?">
              Nein. Ohne deine Freigabe geht nichts online. Du lädst die Clips herunter oder veröffentlichst sie nach der Freigabe über ein verbundenes Konto.
            </Faq>
            <Faq q="Wo landen meine Videos?">
              Nur auf Servern in der EU. Du bekommst einen Auftragsverarbeitungsvertrag, jede Datei hat eine feste Löschfrist und deine Inhalte werden nie zum Trainieren von Modellen verwendet.
            </Faq>
            <Faq q="Klappt das auch mit Dialekt?">
              Österreichisches Deutsch ist voll unterstützt. Schweizerdeutsch läuft als Beta: chopstr markiert Stellen, bei denen es unsicher ist, damit du sie prüfen kannst.
            </Faq>
            <Faq q="Was kostet chopstr?">
              Testen ist kostenlos. Danach zahlst du nach Stunden Video. Keine Credits, keine Punkte, keine Umrechnerei: eine Stunde Material ist eine Stunde.
            </Faq>
          </div>
        </Section>

        {/* Abschluss-CTA */}
        <section className="mx-auto max-w-[1200px] px-4 pb-24 sm:px-8">
          <div className="relative overflow-hidden rounded-card border border-white/10 bg-[linear-gradient(135deg,rgba(2,12,245,0.42)_0%,rgba(20,34,255,0.22)_45%,rgba(27,26,98,0.35)_100%)] px-6 py-14 text-center sm:px-12 sm:py-20">
            <div aria-hidden="true" className="pointer-events-none absolute -right-20 -top-20 h-72 w-72 rounded-full bg-brand/25 blur-3xl" />
            <h2 className="relative mx-auto max-w-[720px] text-3xl font-semibold tracking-[var(--tracking-display)] text-white sm:text-5xl">
              Wie viele gute Clips stecken in deinem letzten Video?
            </h2>
            <p className="relative mx-auto mt-4 max-w-[520px] text-lg text-white/75">Lad es hoch und schau nach. chopstr macht die Vorschläge, du entscheidest.</p>
            <div className="relative mt-8 flex justify-center">
              <PrimaryCta>Kostenlos testen</PrimaryCta>
            </div>
            <p className="relative mt-4 text-sm text-white/60">Ohne Kreditkarte · Daten bleiben in der EU</p>
          </div>
        </section>
      </main>

      <footer className="relative z-10 border-t border-white/[0.06]">
        <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-8 text-sm text-text-3 sm:flex-row sm:items-center sm:justify-between sm:px-8">
          <span>chopstr · EU-verarbeitet · Mensch gibt frei</span>
          <ul className="flex flex-wrap gap-5">
            <li><Link href="/rechtliches/avv" className="hover:text-text-2">AVV</Link></li>
            <li><Link href="/rechtliches/subprozessoren" className="hover:text-text-2">Subprozessoren</Link></li>
            <li><Link href="/rechtliches/toms" className="hover:text-text-2">Sicherheit</Link></li>
            <li><Link href="/anmelden" className="hover:text-text-2">Anmelden</Link></li>
          </ul>
        </div>
      </footer>
    </div>
  );
}

function PrimaryCta({ children, size = "md" }: { children: ReactNode; size?: "sm" | "md" }) {
  return (
    <Link
      href={SIGNUP}
      className={
        "transition-soft inline-flex items-center justify-center rounded-pill bg-text font-medium text-black hover:bg-white hover:shadow-[0_0_32px_rgba(244,245,254,0.25)] " +
        (size === "sm" ? "h-10 px-5 text-sm" : "h-12 px-7 text-[15px]")
      }
    >
      {children}
    </Link>
  );
}

function Check({ children }: { children: ReactNode }) {
  return (
    <li className="flex items-center gap-2">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-ai-soft" aria-hidden="true">
        <path d="M20 6 9 17l-5-5" />
      </svg>
      {children}
    </li>
  );
}

function Section({ id, eyebrow, title, children }: { id?: string; eyebrow: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="mx-auto max-w-[1200px] scroll-mt-20 px-4 py-20 sm:px-8 sm:py-28">
      <div className="mx-auto mb-12 max-w-[720px] text-center">
        <p className="text-sm font-medium text-ai-soft">{eyebrow}</p>
        <h2 className="mt-3 text-3xl font-semibold tracking-[var(--tracking-display)] text-text sm:text-5xl">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function ProblemCard({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-card border border-white/10 bg-white/[0.03] p-6 sm:p-8">
      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-attention/15 text-attention" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 6 6 18M6 6l12 12" /></svg>
      </span>
      <h3 className="mt-5 text-lg font-medium text-text">{title}</h3>
      <p className="mt-2 leading-relaxed text-text-2">{text}</p>
    </div>
  );
}

function Feature({ title, text, className, children }: { title: string; text: string; className?: string; children?: ReactNode }) {
  return (
    <div className={"rounded-card border border-white/10 bg-white/[0.03] p-6 sm:p-8 " + (className ?? "")}>
      <h3 className="text-lg font-medium text-text sm:text-xl">{title}</h3>
      <p className="mt-2 leading-relaxed text-text-2">{text}</p>
      {children}
    </div>
  );
}

function Step({ n, title, text }: { n: number; title: string; text: string }) {
  return (
    <li className="rounded-card border border-white/10 bg-white/[0.03] p-6 sm:p-8">
      <span className="flex h-10 w-10 items-center justify-center rounded-full border border-brand/60 bg-brand/30 font-mono text-sm font-medium text-white">{n}</span>
      <h3 className="mt-5 text-lg font-medium text-text sm:text-xl">{title}</h3>
      <p className="mt-2 leading-relaxed text-text-2">{text}</p>
    </li>
  );
}

function Proof({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-card border border-white/10 bg-white/[0.03] p-6">
      <p className="font-mono text-3xl font-medium tracking-tight text-text">{value}</p>
      <p className="mt-3 text-sm leading-relaxed text-text-2">{label}</p>
    </div>
  );
}

function Faq({ q, children }: { q: string; children: ReactNode }) {
  return (
    <details className="group rounded-inner border border-white/10 bg-white/[0.03] px-5 py-4 open:bg-white/[0.05]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-[16px] font-medium text-text [&::-webkit-details-marker]:hidden">
        {q}
        <span className="transition-soft text-text-3 group-open:rotate-45" aria-hidden="true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
        </span>
      </summary>
      <p className="mt-3 leading-relaxed text-text-2">{children}</p>
    </details>
  );
}
