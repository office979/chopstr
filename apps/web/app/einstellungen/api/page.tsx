import { getApiRepo } from "@/lib/repo/api";
import { requirePageRole } from "@/lib/session";
import { SettingsShell } from "../SettingsShell";
import { ApiKeysPanel } from "./ApiKeysPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "API-Schlüssel" };

export default async function ApiKeysPage() {
  const session = await requirePageRole("api.manage");
  const keys = await getApiRepo().listApiKeys();
  return (
    <SettingsShell
      session={session}
      tab="api"
      title="API-Schlüssel"
      description="Zugang zur öffentlichen API /api/v1 und zum MCP-Server. Jeder Schlüssel hat eigene Scopes und ein Rate-Limit von 600 Anfragen pro Minute."
    >
      <ApiKeysPanel keys={keys} demo={session.demo} />
    </SettingsShell>
  );
}
