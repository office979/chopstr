import { getRepo } from "@/lib/repo";
import { getPublishingRepo } from "@/lib/repo/publishing";
import { requirePublishingPage } from "@/lib/publishing/auth";
import { providerStatus } from "@/lib/publishing/registry";
import { credentialsKeyConfigured } from "@/lib/publishing/crypto";
import { SettingsShell, type SettingsTab } from "../SettingsShell";
import { ConnectionsPanel } from "./ConnectionsPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Verbindungen" };

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

const ERRORS: Record<string, string> = {
  nicht_konfiguriert: "Dieser Provider ist nicht konfiguriert: die App-Zugangsdaten fehlen in der Umgebung (siehe README). Nutze bis dahin die manuelle Verbindung.",
  plattform: "Unbekannte Plattform.",
  state: "Der OAuth-Ablauf konnte nicht zugeordnet werden (State stimmt nicht). Bitte erneut starten.",
  abgelehnt: "Die Plattform hat die Verbindung abgelehnt.",
  code: "Die Plattform hat keinen Code geliefert.",
  austausch: "Der Token-Austausch ist fehlgeschlagen.",
  start: "Der OAuth-Start ist fehlgeschlagen.",
};

/* Verbindungen zu Plattformen (owner, admin): OAuth-Start, manuelle Verbindung, Marke zuordnen, trennen, Capability-Tabelle. */
export default async function ConnectionsPage({ searchParams }: { searchParams: SearchParams }) {
  const session = await requirePublishingPage("publishing.manage");
  const q = await searchParams;
  const [connections, brands] = await Promise.all([getPublishingRepo().listConnections(), getRepo().listBrandProfiles()]);
  const fehler = typeof q.fehler === "string" ? q.fehler : null;
  const plattform = typeof q.plattform === "string" ? q.plattform : null;
  const detail = typeof q.detail === "string" ? q.detail : null;
  const verbunden = typeof q.verbunden === "string" ? q.verbunden : null;
  const notice = fehler
    ? { tone: "error" as const, text: `${ERRORS[fehler] ?? "Unbekannter Fehler."}${plattform ? ` (${plattform})` : ""}${detail ? ` ${detail}` : ""}` }
    : verbunden
      ? { tone: "ok" as const, text: `${verbunden} verbunden.` }
      : null;

  return (
    <SettingsShell
      session={session}
      tab={"verbindungen" as SettingsTab}
      title="Verbindungen"
      description="Plattform-Konten für das Veröffentlichen. Kein Autopublishing: jede Publikation ist eine bestätigte Nutzeraktion."
      width="default"
    >
      <ConnectionsPanel
        initialConnections={connections}
        providers={providerStatus()}
        brands={brands.map((b) => ({ id: b.id, name: b.name }))}
        notice={notice}
        credentialsKey={credentialsKeyConfigured()}
        demo={session.demo}
      />
    </SettingsShell>
  );
}
