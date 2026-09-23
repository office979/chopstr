import Link from "next/link";
import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";
import { ACTION_DENIED, ACTIONS, type Action } from "@/lib/auth/permissions";

export const dynamic = "force-dynamic";
export const metadata = { title: "Kein Zugriff" };

/* 403 für Seiten: requirePageRole() leitet hierher */
export default async function ForbiddenPage({ searchParams }: { searchParams: Promise<{ aktion?: string }> }) {
  const { aktion } = await searchParams;
  const action = (ACTIONS as readonly string[]).includes(aktion ?? "") ? (aktion as Action) : null;
  return (
    <PageShell width="narrow" backgroundWord="403">
      <GlassCard padding="lg" className="text-center">
        <p className="text-lg font-medium">Kein Zugriff</p>
        <p className="mx-auto mt-2 max-w-md text-text-2">{action ? ACTION_DENIED[action] : "Deine Rolle erlaubt diese Aktion nicht."}</p>
        <div className="mt-6 flex justify-center">
          <ButtonLink href="/">Zu den Projekten</ButtonLink>
        </div>
        <p className="mt-6 text-sm text-text-2">
          Falsche Rolle?{" "}
          <Link href="/workspaces" className="text-text hover:underline">
            Team wechseln
          </Link>
        </p>
      </GlassCard>
    </PageShell>
  );
}
