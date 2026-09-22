import Link from "next/link";
import { AuthShell } from "@/components/layout/AuthShell";
import { isDemoMode } from "@/lib/env";
import { RequestResetForm } from "./RequestResetForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Passwort vergessen" };

export default function PasswordRequestPage() {
  const demo = isDemoMode();
  return (
    <AuthShell
      title="Passwort vergessen"
      description="Wir schicken dir einen Link, mit dem du ein neues Passwort setzt. Er ist 15 Minuten gültig."
      backgroundWord="Reset"
      demo={demo}
      footer={
        <Link href="/anmelden" className="text-text hover:underline">
          Zurück zur Anmeldung
        </Link>
      }
    >
      <RequestResetForm demo={demo} />
    </AuthShell>
  );
}
