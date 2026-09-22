import { getRepo } from "@/lib/repo";
import { requireSession } from "@/lib/session";
import { SettingsShell } from "../SettingsShell";
import { SecurityPanel } from "./SecurityPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Sicherheit" };

export default async function SecurityPage() {
  const session = await requireSession();
  const repo = getRepo();
  const [sessions, user] = await Promise.all([session.demo ? Promise.resolve([]) : repo.listUserSessions(session.userId), repo.getUser(session.userId)]);
  return (
    <SettingsShell session={session} tab="sicherheit" title="Sicherheit" description="Deine Sitzungen auf allen Geräten und dein Passwort.">
      <SecurityPanel sessions={sessions} currentSessionId={session.sessionId} hasPassword={Boolean(user?.password_hash)} demo={session.demo} />
    </SettingsShell>
  );
}
