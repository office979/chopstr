import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthShell } from "@/components/layout/AuthShell";
import { isDemoMode } from "@/lib/env";
import { getAuthUser } from "@/lib/session";
import { RegisterForm } from "./RegisterForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Registrieren" };

export default async function RegisterPage() {
  const demo = isDemoMode();
  if (!demo && (await getAuthUser())) redirect("/");
  return (
    <AuthShell
      title="Konto anlegen"
      description="Ein Konto für dich, ein Team für deine Firma. Mitglieder lädst du danach ein."
      backgroundWord="Start"
      demo={demo}
      footer={
        <>
          <span>Schon ein Konto?</span>
          <Link href="/anmelden" className="text-text hover:underline">
            Anmelden
          </Link>
        </>
      }
    >
      <RegisterForm demo={demo} />
    </AuthShell>
  );
}
