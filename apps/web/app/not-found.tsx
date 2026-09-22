import { PageShell } from "@/components/layout/PageShell";
import { GlassCard } from "@/components/ui/GlassCard";
import { ButtonLink } from "@/components/ui/Button";

export default function NotFound() {
  return (
    <PageShell width="narrow" backgroundWord="404">
      <GlassCard padding="lg" className="text-center">
        <p className="text-lg font-medium">Seite nicht gefunden</p>
        <p className="mx-auto mt-2 max-w-md text-text-2">Das Projekt existiert nicht oder wurde nach Ablauf der Löschfrist entfernt.</p>
        <div className="mt-6 flex justify-center">
          <ButtonLink href="/">Zu den Projekten</ButtonLink>
        </div>
      </GlassCard>
    </PageShell>
  );
}
