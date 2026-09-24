import { PageShell } from "@/components/layout/PageShell";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requireSession } from "@/lib/session";
import { canExt } from "@/lib/auth/permissions-publishing";
import { formatDate, formatDateTime } from "@/lib/format";
import type { WeeklyReportClipEntry } from "@/lib/repo/types-publishing";
import { ButtonLink } from "@/components/ui/Button";
import { getRepo } from "@/lib/repo";
import { ReportSettings } from "./ReportSettings";

export const dynamic = "force-dynamic";
export const metadata = { title: "Berichte" };

function Entry({ e, tone }: { e: WeeklyReportClipEntry; tone: "ok" | "attention" }) {
  return (
    <li className="rounded-inner border border-line p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">{e.title ?? `Clip ${e.clip_id.slice(0, 8)}`}</span>
        <span className="flex items-center gap-2">
          {e.platform && <Badge className="h-6 px-2.5 text-[11px]">{e.platform}</Badge>}
          <Badge tone={tone} className="h-6 px-2.5 font-mono text-[11px]">
            {e.follows_per_1k != null
              ? `${e.follows_per_1k.toLocaleString("de-AT", { maximumFractionDigits: 2 })} neue Folgende je 1.000 Aufrufe`
              : "keine Folgezahlen"}
          </Badge>
        </span>
      </div>
      {e.views != null && <p className="mt-1 font-mono text-xs text-text-3">{e.views.toLocaleString("de-AT")} Aufrufe</p>}
      {/* „Ursache" behauptet Wissen, das eine Rechnung über eine Handvoll Clips nicht hergibt.
          Was hier steht, ist eine Vermutung - und daneben etwas, das sich ausprobieren lässt. */}
      {e.cause && (
        <p className="mt-2 text-text-2">
          <span className="text-text">Mögliche Ursache:</span> {e.cause}
        </p>
      )}
      {e.change && (
        <p className="mt-1 text-text-2">
          <span className="text-text">Nächster Versuch:</span> {e.change}
        </p>
      )}
    </li>
  );
}

/* Wochenberichte des Workspace: 3 beste und 3 schwächste Clips nach Folgequote mit Ursache und Änderung */
export default async function ReportsPage() {
  const session = await requireSession();
  const pub = getPublishingRepo();
  const [reports, enabled] = await Promise.all([pub.listWeeklyReports(), pub.getWeeklyReportEnabled()]);
  const canManage = canExt(session.role, "publishing.manage");
  const naechster = reports.length === 0 ? await naechsterSchritt() : { satz: "", knopf: "", pfad: null };
  /* Versendet wird über SMTP. Ohne eingerichteten Versand landet die Mail in der Serverkonsole -
   * „aktiv" zu behaupten wäre dann eine Zusage, die niemand einlöst. */
  const versandMoeglich = Boolean(process.env.SMTP_URL);
  const empfaenger = canManage ? await empfaengerListe() : [];

  return (
    <PageShell width="default" backgroundWord="Woche">
      {/* „Folgequote" und „Ursache" waren Behauptungen: die eine ein Fachwort, die andere eine
          Gewissheit, die eine Rechnung über wenige Clips nicht hergibt. */}
      <PageHeader
        eyebrow={`Team · ${session.workspaceName}`}
        title="Berichte"
        description="Jeden Montag eine Rückschau auf die Woche: welche Clips am besten liefen, welche am schwächsten, und ein Vorschlag, was du beim nächsten Mal anders machen kannst."
      />
      <GlassCard padding="md" className="mb-5">
        <ReportSettings enabled={enabled} canManage={canManage} versandMoeglich={versandMoeglich} empfaenger={empfaenger} />
      </GlassCard>
      {reports.length === 0 ? (
        /* Die Leerseite nennt den Schritt, der WIRKLICH als Nächstes möglich ist.
           Vorher verwies sie auf Serien und Tests - beide liefern die Daten nicht, und der
           Nutzer lief in zwei weitere leere Seiten. Ein Bericht braucht drei Dinge in dieser
           Reihenfolge: einen freigegebenen Clip, den Vermerk, dass er gepostet wurde, und die
           Zahlen dazu. Genau da steht der Nutzer gerade, und genau dorthin führt der Knopf. */
        <GlassCard padding="lg" className="flex flex-col items-center gap-4 text-center">
          <div>
            <p className="text-lg font-medium">Noch kein Bericht</p>
            <p className="mx-auto mt-2 max-w-lg text-text-2">{naechster.satz}</p>
          </div>
          {naechster.pfad && <ButtonLink href={naechster.pfad}>{naechster.knopf}</ButtonLink>}
        </GlassCard>
      ) : (
        <ul className="flex flex-col gap-5">
          {reports.map((r) => (
            <li key={r.id}>
              <GlassCard padding="lg">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h2 className="text-lg font-medium">Woche ab {formatDate(r.week_start)}</h2>
                  {/* Woher die Zahlen kommen und worauf sie sich stützen. Ohne das ist „bester
                      Clip" eine Behauptung ohne Grundlage - bei zwei verglichenen Clips heisst
                      „der beste" etwas anderes als bei zwanzig. */}
                  <p className="text-xs text-text-2">
                    {r.report.clips != null ? `${r.report.clips} ${r.report.clips === 1 ? "Clip" : "Clips"} verglichen · ` : ""}
                    {r.report.publications != null ? `${r.report.publications} gepostet · ` : ""}
                    {r.sent_at ? `Stand ${formatDateTime(r.sent_at)}` : "noch nicht versendet"}
                  </p>
                </div>
                {r.report.summary && <p className="mt-2 text-sm text-text-2">{r.report.summary}</p>}
                <div className="mt-4 grid gap-5 md:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Lief am besten</h3>
                    {(r.report.best ?? []).length === 0 ? <p className="text-sm text-text-2">Keine Daten.</p> : <ul className="flex flex-col gap-2">{(r.report.best ?? []).map((e) => <Entry key={e.clip_id} e={e} tone="ok" />)}</ul>}
                  </div>
                  <div>
                    <h3 className="mb-2 text-sm font-medium">Lief am schwächsten</h3>
                    {(r.report.worst ?? []).length === 0 ? <p className="text-sm text-text-2">Keine Daten.</p> : <ul className="flex flex-col gap-2">{(r.report.worst ?? []).map((e) => <Entry key={e.clip_id} e={e} tone="attention" />)}</ul>}
                  </div>
                </div>
              </GlassCard>
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}

/* Was fehlt, damit ein Bericht entstehen kann - und der Weg dorthin.
 *
 * Ein Bericht braucht drei Dinge nacheinander: einen freigegebenen Clip, den Vermerk, dass er
 * gepostet wurde, und die Zahlen dazu. Diese Funktion sagt, an welchem der drei Punkte der
 * Nutzer gerade steht. Vorher stand auf der Leerseite ein Verweis auf Serien und Tests - beide
 * liefern die Daten nicht, und beide sind selbst leer. */
async function naechsterSchritt(): Promise<{ satz: string; knopf: string; pfad: string | null }> {
  const repo = getRepo();
  const quellen = await repo.listSources();
  let ersteMitClips: string | null = null;
  let ersteMitFreigabe: string | null = null;
  for (const q of quellen) {
    if (q.status !== "ready") continue;
    const clips = await repo.listClips(q.id);
    if (clips.length === 0) continue;
    ersteMitClips ??= q.id;
    if (clips.some((c) => c.review === "bereit")) {
      ersteMitFreigabe = q.id;
      break;
    }
  }
  if (ersteMitFreigabe) {
    return {
      satz: "Du hast freigegebene Clips. Sobald du an einem davon einträgst, dass du ihn gepostet hast, und die Aufrufe dazuschreibst, entsteht am Montag der erste Bericht.",
      knopf: "Zu den freigegebenen Clips",
      pfad: `/projekte/${ersteMitFreigabe}/clips#postbereit`,
    };
  }
  if (ersteMitClips) {
    return {
      satz: "Ein Bericht schaut auf Clips zurück, die du gepostet hast. Der erste Schritt dahin: einen Clip prüfen und freigeben.",
      knopf: "Clips prüfen",
      pfad: `/projekte/${ersteMitClips}/clips`,
    };
  }
  return {
    satz: "Ein Bericht schaut auf Clips zurück, die du gepostet hast. Dafür fehlt noch ein Video.",
    knopf: "Neues Video",
    pfad: "/upload",
  };
}

/* Wer die Montagsmail bekommt. Derselbe Kreis, den der Versand im Hintergrund anschreibt:
 * Inhaber und Verwaltende des Teams. */
async function empfaengerListe(): Promise<string[]> {
  try {
    const mitglieder = await getRepo().listMembers();
    return mitglieder
      .filter((m) => m.role === "owner" || m.role === "admin")
      .map((m) => m.email)
      .filter((e): e is string => Boolean(e));
  } catch {
    return [];
  }
}
