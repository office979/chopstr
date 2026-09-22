import Link from "next/link";
import { AuthShell } from "@/components/layout/AuthShell";
import { isDemoMode } from "@/lib/env";
import { ResetForm } from "./ResetForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Neues Passwort" };

/* Das Token wird erst beim Absenden geprüft und verbraucht (Mail-Scanner öffnen Links) */
export default async function PasswordResetPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const demo = isDemoMode();
  return (
    <AuthShell
      title="Neues Passwort"
      description="Nach dem Speichern werden alle anderen Sitzungen beendet und du bist direkt angemeldet."
      backgroundWord="Reset"
      demo={demo}
      footer={
        <Link href="/anmelden" className="text-text hover:underline">
          Zurück zur Anmeldung
        </Link>
      }
    >
      <ResetForm token={token} demo={demo} />
    </AuthShell>
  );
}
