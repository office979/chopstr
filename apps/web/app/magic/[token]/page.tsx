import Link from "next/link";
import { AuthShell } from "@/components/layout/AuthShell";
import { ConfirmForm } from "@/components/ui/ConfirmForm";
import { isDemoMode } from "@/lib/env";
import { safeNext } from "@/lib/auth/url";
import { confirmMagicAction } from "./actions";

export const dynamic = "force-dynamic";
export const metadata = { title: "Anmeldelink" };

/* Der Link wird erst per Button eingelöst, damit Mail-Scanner das Token nicht verbrauchen */
export default async function MagicPage({ params, searchParams }: { params: Promise<{ token: string }>; searchParams: Promise<{ next?: string }> }) {
  const { token } = await params;
  const { next } = await searchParams;
  const demo = isDemoMode();
  return (
    <AuthShell
      title="Anmeldung bestätigen"
      description="Mit einem Klick bist du angemeldet. Der Link ist 15 Minuten gültig und nur einmal nutzbar."
      backgroundWord="Link"
      demo={demo}
      footer={
        <Link href="/anmelden" className="text-text hover:underline">
          Zurück zur Anmeldung
        </Link>
      }
    >
      <ConfirmForm action={confirmMagicAction} label="Jetzt anmelden" pendingLabel="Wird geprüft" hidden={{ token, next: safeNext(next) }} disabled={demo} />
    </AuthShell>
  );
}
