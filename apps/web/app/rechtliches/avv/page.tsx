import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { getRepo } from "@/lib/repo";
import { getSession } from "@/lib/session";
import { can } from "@/lib/auth/permissions";
import { DPA_VERSION, fillPlaceholders, loadLegalDoc } from "@/lib/legal/docs";
import { Markdown } from "@/lib/legal/Markdown";
import { formatDateTime } from "@/lib/format";
import { LegalShell } from "../LegalShell";
import { DpaAcceptForm } from "./DpaAcceptForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "AVV" };

/* AVV nach Art. 28 DSGVO: Platzhalter aus dem Workspace, Annahme durch owner/admin (PHASE4.md, Abschnitt 6) */
export default async function DpaPage() {
  const doc = loadLegalDoc("avv");
  const session = await getSession();
  const repo = getRepo();
  const [workspace, acceptance, subscription] = session
    ? await Promise.all([repo.getWorkspace(), repo.getDpaAcceptance(), repo.getSubscription()])
    : [null, null, null];
  const address = subscription?.billing_address;
  const addressLine = address?.street ? [address.street, [address.zip, address.city].filter(Boolean).join(" "), address.country].filter(Boolean).join(", ") : null;

  const markdown = doc
    ? fillPlaceholders(doc.markdown, {
        company: acceptance?.company ?? address?.company ?? workspace?.name ?? null,
        representative: acceptance?.representative ?? null,
        address: addressLine,
        retention_days: workspace?.retention_days ?? null,
        render_retention_days: workspace?.render_retention_days ?? null,
        accepted_at: acceptance?.accepted_at ?? null,
        ip: acceptance?.ip ?? null,
        version: acceptance?.dpa_version ?? doc.version,
      })
    : "";
  const canAccept = Boolean(session && can(session.role, "dpa.accept"));
  const signed = Boolean(workspace?.dpa_signed_at);

  const aside = session ? (
    <>
      <GlassCard padding="lg" className="flex flex-col gap-3">
        <h2 className="text-lg font-medium">Status</h2>
        {signed ? (
          <>
            <Badge tone="ok">Angenommen</Badge>
            <p className="text-sm text-text-2">
              {acceptance ? (
                <>
                  Version {acceptance.dpa_version} am {formatDateTime(acceptance.accepted_at)}
                  {acceptance.accepted_by_label ? ` durch ${acceptance.accepted_by_label}` : ""}
                  {acceptance.company ? ` für ${acceptance.company}` : ""}.
                </>
              ) : (
                <>Angenommen am {formatDateTime(workspace?.dpa_signed_at)}.</>
              )}
            </p>
            {acceptance && acceptance.dpa_version !== DPA_VERSION && <p className="text-sm text-attention">Es gibt eine neuere Version ({DPA_VERSION}). Bitte erneut annehmen.</p>}
          </>
        ) : (
          <>
            <Badge tone="attention">Noch nicht angenommen</Badge>
            <p className="text-sm text-text-2">Uploads sind möglich, der Auftragsverarbeitungsvertrag fehlt aber. {canAccept ? "Du kannst ihn hier annehmen." : "Bitte einen Inhaber oder Admin."}</p>
          </>
        )}
        <p className="text-xs text-text-2">
          Anlagen: <Link href="/rechtliches/toms" className="text-text hover:underline">TOMs</Link> und{" "}
          <Link href="/rechtliches/subprozessoren" className="text-text hover:underline">Subprozessoren</Link> je Tarif ({workspace?.tier === "sovereign" ? "Sovereign" : "Standard"}).
        </p>
      </GlassCard>
      {canAccept && (!signed || (acceptance && acceptance.dpa_version !== DPA_VERSION)) && (
        <DpaAcceptForm version={DPA_VERSION} defaultCompany={acceptance?.company ?? address?.company ?? workspace?.name ?? ""} defaultRepresentative={acceptance?.representative ?? session.displayName} />
      )}
    </>
  ) : (
    <GlassCard padding="lg" className="flex flex-col gap-2">
      <h2 className="text-lg font-medium">Für deinen Workspace</h2>
      <p className="text-sm text-text-2">
        Nach der <Link href="/anmelden?next=/rechtliches/avv" className="text-text hover:underline">Anmeldung</Link> werden Firma, Vertreter und Löschfristen aus dem Workspace eingesetzt und Inhaber können den Vertrag annehmen.
      </p>
    </GlassCard>
  );

  return (
    <LegalShell current="avv" doc={doc} title="Auftragsverarbeitung" eyebrow="Rechtliches · Art. 28 DSGVO" aside={aside}>
      {doc && <Markdown source={markdown} />}
    </LegalShell>
  );
}
