import Link from "next/link";
import { redirect } from "next/navigation";
import { AuthShell } from "@/components/layout/AuthShell";
import { isDemoMode } from "@/lib/env";
import { getAuthUser } from "@/lib/session";
import { safeNext } from "@/lib/auth/url";
import { LoginForm } from "./LoginForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Anmelden" };

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ next?: string }> }) {
  const { next } = await searchParams;
  const target = safeNext(next);
  const demo = isDemoMode();
  if (!demo && (await getAuthUser())) redirect(target);

  return (
    <AuthShell
      title="Anmelden"
      description="Mit E-Mail und Passwort oder per Magic-Link. Deine Daten bleiben in der EU."
      demo={demo}
      footer={
        <>
          <span>Noch kein Konto?</span>
          <Link href="/registrieren" className="text-text hover:underline">
            Workspace anlegen
          </Link>
        </>
      }
    >
      <LoginForm next={target} demo={demo} />
    </AuthShell>
  );
}
