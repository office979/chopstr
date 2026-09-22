import Link from "next/link";
import { AuthShell } from "@/components/layout/AuthShell";
import { ConfirmForm } from "@/components/ui/ConfirmForm";
import { isDemoMode } from "@/lib/env";
import { verifyEmailAction } from "./actions";

export const dynamic = "force-dynamic";
export const metadata = { title: "E-Mail bestätigen" };

export default async function VerifyPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const demo = isDemoMode();
  return (
    <AuthShell
      title="E-Mail-Adresse bestätigen"
      description="Bestätige mit einem Klick, dass diese Adresse dir gehört."
      backgroundWord="Mail"
      demo={demo}
      footer={
        <Link href="/profil" className="text-text hover:underline">
          Zum Profil
        </Link>
      }
    >
      <ConfirmForm action={verifyEmailAction} label="Adresse bestätigen" pendingLabel="Wird geprüft" hidden={{ token }} disabled={demo} />
    </AuthShell>
  );
}
