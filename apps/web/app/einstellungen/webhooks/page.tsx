import { getApiRepo } from "@/lib/repo/api";
import { requirePageRole } from "@/lib/session";
import { SettingsShell } from "../SettingsShell";
import { WebhooksPanel } from "./WebhooksPanel";

export const dynamic = "force-dynamic";
export const metadata = { title: "Webhooks" };

export default async function WebhooksPage() {
  const session = await requirePageRole("api.manage");
  const apiRepo = getApiRepo();
  const [endpoints, deliveries] = await Promise.all([apiRepo.listWebhookEndpoints(), apiRepo.listWebhookDeliveries(100)]);
  return (
    <SettingsShell
      session={session}
      tab="webhooks"
      title="Webhooks"
      description="Statuswechsel als signierte POST-Anfragen an deine Systeme: Quelle bereit, Clip gerendert, Gast hat entschieden, Veröffentlichung, Kontingent."
      width="default"
    >
      <WebhooksPanel endpoints={endpoints} deliveries={deliveries} demo={session.demo} />
    </SettingsShell>
  );
}
