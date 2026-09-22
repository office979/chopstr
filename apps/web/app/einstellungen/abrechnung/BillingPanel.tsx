"use client";

import { useActionState, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { GlassCard } from "@/components/ui/GlassCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field, Input, Select } from "@/components/ui/Field";
import { FormNotice } from "@/components/ui/FormNotice";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/components/ui/cn";
import { initialFormState } from "@/lib/auth/form";
import type { Plan, Subscription, UsagePeriod } from "@/lib/repo/types";
import { PLAN_ORDER, STATUS_LABELS, formatEur, formatHoursLong, formatPeriod, isTrialExpired, summarizeUsage } from "@/lib/billing/format";
import { formatDate } from "@/lib/format";
import { updateBillingAddressAction } from "./actions";

interface Props {
  provider: "manual" | "stripe";
  subscription: Subscription | null;
  plan: Plan | null;
  plans: Plan[];
  usage: UsagePeriod | null;
  history: UsagePeriod[];
  workspaceName: string;
  workspaceTier: "standard" | "sovereign";
  notice: string | null;
  demo: boolean;
}

interface PlanResponse {
  error?: string;
  redirect_url?: string;
  subscription?: Subscription;
  message?: string;
}

const COUNTRY_OPTIONS: [string, string][] = [
  ["AT", "Österreich"],
  ["DE", "Deutschland"],
  ["CH", "Schweiz"],
  ["IT", "Italien"],
  ["FR", "Frankreich"],
  ["NL", "Niederlande"],
  ["BE", "Belgien"],
  ["LU", "Luxemburg"],
  ["LI", "Liechtenstein"],
  ["PL", "Polen"],
  ["CZ", "Tschechien"],
  ["SK", "Slowakei"],
  ["HU", "Ungarn"],
  ["SI", "Slowenien"],
  ["HR", "Kroatien"],
  ["DK", "Dänemark"],
  ["SE", "Schweden"],
  ["FI", "Finnland"],
  ["NO", "Norwegen"],
  ["IE", "Irland"],
  ["ES", "Spanien"],
  ["PT", "Portugal"],
];

function statusTone(status: Subscription["status"] | null): "neutral" | "ok" | "attention" | "ai" | "danger" {
  switch (status) {
    case "active":
      return "ok";
    case "trialing":
      return "ai";
    case "past_due":
      return "attention";
    case "canceled":
      return "danger";
    default:
      return "neutral";
  }
}

/* Abrechnungsseite: Plan und Status, Verbrauchsbalken mit Prognose, Planvergleich, Rechnungsadresse, Verlauf */
export function BillingPanel({ provider, subscription, plan, plans, usage, history, workspaceName, workspaceTier, notice, demo }: Props) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(notice ? { tone: "ok", text: notice } : null);
  const [confirmPlan, setConfirmPlan] = useState<Plan | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [addressState, addressAction, addressPending] = useActionState(updateBillingAddressAction, initialFormState);

  const summary = summarizeUsage(usage, plan);
  const status = subscription?.status ?? null;
  const trialExpired = isTrialExpired(subscription);
  const orderedPlans = [...plans].sort((a, b) => PLAN_ORDER.indexOf(a.code as (typeof PLAN_ORDER)[number]) - PLAN_ORDER.indexOf(b.code as (typeof PLAN_ORDER)[number]));
  const address = subscription?.billing_address ?? {};

  const call = async (body: Record<string, unknown>, key: string) => {
    setBusy(key);
    setMessage(null);
    try {
      const res = await fetch("/api/billing/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = (await res.json()) as PlanResponse;
      if (!res.ok) throw new Error(data.error ?? "Aktion fehlgeschlagen");
      if (data.redirect_url) {
        window.location.assign(data.redirect_url);
        return;
      }
      setMessage({ tone: "ok", text: data.message ?? "Gespeichert." });
      setConfirmPlan(null);
      setConfirmCancel(false);
      router.refresh();
    } catch (err) {
      setMessage({ tone: "error", text: err instanceof Error ? err.message : "Aktion fehlgeschlagen" });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {message && (
        <p role="status" aria-live="polite" className={cn("rounded-inner border px-4 py-3 text-sm", message.tone === "ok" ? "border-line text-text" : "border-attention/50 bg-attention/10 text-text")}>
          {message.text}
        </p>
      )}

      {/* Plan und Status */}
      <GlassCard padding="lg" className="flex flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-sm text-text-2">Aktueller Tarif</p>
            <p className="mt-1 text-3xl font-semibold tracking-[var(--tracking-display)]">{plan?.name ?? "Kein Tarif"}</p>
            {plan && (
              <p className="mt-1 text-sm text-text-2">
                {formatEur(plan.monthly_eur)} pro Monat, {formatHoursLong(plan.included_hours * 60)} Quellmaterial inklusive, danach {formatEur(plan.overage_eur_per_hour)} je angefangener Stunde.
              </p>
            )}
          </div>
          <div className="flex flex-col items-start gap-2 sm:items-end">
            <Badge tone={statusTone(status)}>{status ? STATUS_LABELS[status] : "kein Abo"}</Badge>
            {subscription?.cancel_at_period_end && <Badge tone="attention">Gekündigt zum {formatDate(subscription.current_period_end)}</Badge>}
            {trialExpired && <Badge tone="attention">Testphase abgelaufen</Badge>}
          </div>
        </div>
        <dl className="grid gap-4 border-t border-line pt-5 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-text-2">Zeitraum</dt>
            <dd className="mt-1 text-text">
              {subscription?.current_period_start ? `${formatDate(subscription.current_period_start)} bis ${formatDate(subscription.current_period_end)}` : "offen"}
            </dd>
          </div>
          <div>
            <dt className="text-text-2">{status === "trialing" ? "Testende" : "Nächste Abrechnung"}</dt>
            <dd className="mt-1 text-text">{status === "trialing" ? formatDate(subscription?.trial_ends_at) : subscription?.current_period_end ? formatDate(subscription.current_period_end) : "offen"}</dd>
          </div>
          <div>
            <dt className="text-text-2">Zahlung</dt>
            <dd className="mt-1 text-text">
              {provider === "stripe" && subscription?.provider === "stripe" ? "Stripe" : "Rechnung per E-Mail"}
              {subscription?.billing_email ? ` an ${subscription.billing_email}` : ""}
            </dd>
          </div>
        </dl>
        <div className="flex flex-wrap items-center gap-2 border-t border-line pt-5">
          {provider === "stripe" && subscription?.provider === "stripe" && (
            <a href="/api/billing/portal" className="transition-soft inline-flex h-9 items-center rounded-pill border border-line-strong px-4 text-sm text-text hover:bg-white/5">
              Rechnungen und Zahlungsmittel (Stripe)
            </a>
          )}
          {subscription && status !== "canceled" && !subscription.cancel_at_period_end && status !== "trialing" && (
            <Button variant="danger" size="sm" onClick={() => setConfirmCancel(true)} disabled={busy != null}>
              Zum Periodenende kündigen
            </Button>
          )}
          {subscription?.cancel_at_period_end && (
            <Button variant="ghost" size="sm" onClick={() => call({ cancel_at_period_end: false }, "revoke")} disabled={busy != null}>
              {busy === "revoke" ? "Wird gespeichert" : "Kündigung zurücknehmen"}
            </Button>
          )}
          <span className="text-xs text-text-2">
            {provider === "manual" ? "Kein Zahlungsanbieter konfiguriert: Tarifwechsel gelten sofort, die Rechnung kommt per E-Mail." : "Zahlungen laufen über Stripe (EU-Entität)."}
            {demo ? " Demo: nur im Speicher." : ""}
          </span>
        </div>
      </GlassCard>

      {/* Verbrauch */}
      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 className="text-lg font-medium">Verbrauch {usage ? formatPeriod(usage.period_start) : "diesen Monat"}</h2>
          <span className="font-mono text-sm tabular-nums text-text">
            {formatHoursLong(summary.used_minutes)} von {formatHoursLong(summary.included_minutes)}
          </span>
        </div>
        <div
          className="relative h-2.5 w-full overflow-hidden rounded-pill bg-white/10"
          role="progressbar"
          aria-label="Stunden Quellmaterial"
          aria-valuemin={0}
          aria-valuemax={Math.round(summary.included_minutes)}
          aria-valuenow={Math.round(summary.used_minutes)}
        >
          <div className={cn("h-full rounded-pill", summary.overage_minutes > 0 ? "bg-attention" : "bg-text")} style={{ width: `${Math.max(2, Math.round(summary.ratio * 100))}%` }} />
          {summary.included_minutes > 0 && summary.forecast_minutes > summary.used_minutes && (
            <div
              aria-hidden="true"
              className="absolute top-0 h-full border-r border-dashed border-ai-soft"
              style={{ left: `${Math.min(100, Math.round((summary.forecast_minutes / summary.included_minutes) * 100))}%` }}
              title="Prognose"
            />
          )}
        </div>
        <dl className="grid gap-4 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-text-2">Prognose Monatsende</dt>
            <dd className="mt-1 text-text">
              {formatHoursLong(summary.forecast_minutes)}
              <span className="block text-xs text-text-2">
                Tag {summary.days_elapsed} von {summary.days_total}, linear hochgerechnet
              </span>
            </dd>
          </div>
          <div>
            <dt className="text-text-2">Mehrverbrauch bisher</dt>
            <dd className={cn("mt-1", summary.overage_minutes > 0 ? "text-attention" : "text-text")}>
              {summary.overage_minutes > 0 ? `${formatHoursLong(summary.overage_minutes)}, ${formatEur(summary.overage_eur)}` : "keiner"}
            </dd>
          </div>
          <div>
            <dt className="text-text-2">Erwarteter Mehrverbrauch</dt>
            <dd className="mt-1 text-text">{summary.forecast_overage_eur > 0 ? formatEur(summary.forecast_overage_eur) : formatEur(0)}</dd>
          </div>
          <div>
            <dt className="text-text-2">Renders</dt>
            <dd className="mt-1 text-text">{usage?.render_count ?? 0}</dd>
          </div>
        </dl>
        <p className="text-xs text-text-2">
          Gezählt wird die Dauer des Quellmaterials beim Ingest (job_costs, Typ ingest). Mehrverbrauch wird pro angefangener Stunde berechnet
          {status === "trialing" ? "; in der Testphase ist er gesperrt, Uploads enden am Kontingent." : "."}
        </p>
      </GlassCard>

      {/* Planvergleich */}
      <GlassCard padding="lg" className="flex flex-col gap-4">
        <div>
          <h2 className="text-lg font-medium">Tarife</h2>
          <p className="mt-1 text-sm text-text-2">Preise pro Monat, netto. Sovereign läuft ausschließlich bei EU-Anbietern ohne US-Konzernmutter.</p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {orderedPlans.map((p) => {
            const current = plan?.code === p.code;
            const gated = p.code === "sovereign" && workspaceTier !== "sovereign";
            return (
              <li key={p.code} className={cn("flex flex-col gap-3 rounded-inner border p-4", current ? "glass-selected border-ai-soft/50" : "border-line")}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-base font-medium">{p.name}</span>
                  {current && (
                    <Badge tone="ai" className="h-6 px-2.5 text-[11px]">
                      Aktuell
                    </Badge>
                  )}
                </div>
                <p className="text-2xl font-semibold tracking-[var(--tracking-display)]">{formatEur(p.monthly_eur)}</p>
                <ul className="flex flex-col gap-1 text-sm text-text-2">
                  <li>{formatHoursLong(p.included_hours * 60)} Quellmaterial</li>
                  <li>{formatEur(p.overage_eur_per_hour)} je weitere Stunde</li>
                  <li>{p.max_brand_profiles == null ? "Unbegrenzt Markenprofile" : `${p.max_brand_profiles} ${p.max_brand_profiles === 1 ? "Markenprofil" : "Markenprofile"}`}</li>
                  <li>{p.max_members == null ? "Unbegrenzt Mitglieder" : `${p.max_members} Mitglieder`}</li>
                  <li className={p.features?.guest_approval ? "text-text" : ""}>{p.features?.guest_approval ? "Gast-Freigabe" : "Keine Gast-Freigabe"}</li>
                  {Boolean(p.features?.white_label) && <li className="text-text">White-Label</li>}
                  {Boolean(p.features?.sovereign) && <li className="text-text">Sovereign-Hosting</li>}
                </ul>
                <div className="mt-auto pt-2">
                  {current && status !== "trialing" && !subscription?.cancel_at_period_end ? (
                    <span className="text-xs text-text-2">Dein Tarif</span>
                  ) : gated ? (
                    <span className="text-xs text-text-2">Nur für Sovereign-Workspaces (Umstellung über den Support)</span>
                  ) : (
                    <Button size="sm" variant={current ? "primary" : "ghost"} onClick={() => setConfirmPlan(p)} disabled={busy != null}>
                      {current ? "Jetzt buchen" : plan && p.monthly_eur > plan.monthly_eur ? "Upgrade" : "Wechseln"}
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </GlassCard>

      {/* Rechnungsadresse */}
      <form action={addressAction} noValidate>
        <GlassCard padding="lg" className="flex flex-col gap-5">
          <div>
            <h2 className="text-lg font-medium">Rechnungsadresse</h2>
            <p className="mt-1 text-sm text-text-2">Erscheint auf jeder Rechnung. Die UID macht die Rechnung innerhalb der EU umsatzsteuerfrei (Reverse Charge).</p>
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Firma" htmlFor="company" required error={addressState.errors.company} className="sm:col-span-2">
              <Input id="company" name="company" defaultValue={address.company ?? workspaceName} autoComplete="organization" />
            </Field>
            <Field label="Straße und Hausnummer" htmlFor="street" required error={addressState.errors.street} className="sm:col-span-2">
              <Input id="street" name="street" defaultValue={address.street ?? ""} autoComplete="street-address" />
            </Field>
            <Field label="PLZ" htmlFor="zip" required error={addressState.errors.zip}>
              <Input id="zip" name="zip" defaultValue={address.zip ?? ""} autoComplete="postal-code" />
            </Field>
            <Field label="Ort" htmlFor="city" required error={addressState.errors.city}>
              <Input id="city" name="city" defaultValue={address.city ?? ""} autoComplete="address-level2" />
            </Field>
            <Field label="Land" htmlFor="country" required error={addressState.errors.country}>
              <Select id="country" name="country" defaultValue={address.country ?? "AT"}>
                {COUNTRY_OPTIONS.map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="UID" htmlFor="vat_id" hint="Optional, z. B. ATU12345678." error={addressState.errors.vat_id}>
              <Input id="vat_id" name="vat_id" defaultValue={address.vat_id ?? ""} autoComplete="off" />
            </Field>
            <Field label="Rechnungs-E-Mail" htmlFor="billing_email" error={addressState.errors.billing_email} className="sm:col-span-2">
              <Input id="billing_email" name="billing_email" type="email" defaultValue={subscription?.billing_email ?? ""} autoComplete="email" />
            </Field>
          </div>
          <FormNotice state={addressState} />
          <div className="flex justify-end">
            <Button type="submit" disabled={addressPending}>
              {addressPending ? "Wird gespeichert" : "Adresse speichern"}
            </Button>
          </div>
        </GlassCard>
      </form>

      {/* Verlauf */}
      <GlassCard padding="none" className="overflow-hidden">
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-lg font-medium">Verlauf</h2>
          <p className="mt-1 text-sm text-text-2">Vergangene Monate mit Verbrauch und Mehrverbrauch.</p>
        </div>
        {history.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-text-2">Noch kein abgeschlossener Monat.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-text-2">
                <tr>
                  <th className="px-5 py-3 font-medium">Monat</th>
                  <th className="px-3 py-3 font-medium">Verbraucht</th>
                  <th className="px-3 py-3 font-medium">Inklusive</th>
                  <th className="px-3 py-3 font-medium">Renders</th>
                  <th className="px-3 py-3 font-medium">Mehrverbrauch</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {history.map((h) => (
                  <tr key={h.id}>
                    <td className="px-5 py-3 text-text">{formatPeriod(h.period_start)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums text-text">{formatHoursLong(h.used_source_minutes)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums text-text-2">{formatHoursLong(h.included_minutes)}</td>
                    <td className="px-3 py-3 font-mono tabular-nums text-text-2">{h.render_count}</td>
                    <td className={cn("px-3 py-3 font-mono tabular-nums", h.overage_eur > 0 ? "text-attention" : "text-text-2")}>
                      {h.overage_eur > 0 ? `${formatHoursLong(h.overage_minutes)}, ${formatEur(h.overage_eur)}` : "keiner"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </GlassCard>

      <p className="text-xs text-text-2">
        Fragen zur Rechnung? <Link href="/rechtliches/avv" className="text-text hover:underline">AVV</Link> und Subprozessoren findest du unter Rechtliches.
      </p>

      <Modal
        open={confirmPlan != null}
        onClose={() => busy == null && setConfirmPlan(null)}
        title={confirmPlan ? `Tarif ${confirmPlan.name} wählen` : "Tarif wählen"}
        description={
          confirmPlan
            ? `${formatEur(confirmPlan.monthly_eur)} pro Monat mit ${formatHoursLong(confirmPlan.included_hours * 60)} Quellmaterial. ${
                provider === "stripe" ? "Du wirst zu Stripe weitergeleitet oder das bestehende Abo wird anteilig umgestellt." : "Der Wechsel gilt sofort, die Rechnung kommt per E-Mail."
              }`
            : undefined
        }
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmPlan(null)} disabled={busy != null}>
            Abbrechen
          </Button>
          <Button onClick={() => confirmPlan && call({ plan_code: confirmPlan.code }, "plan")} disabled={busy != null}>
            {busy === "plan" ? "Wird umgestellt" : provider === "stripe" ? "Weiter" : "Tarif übernehmen"}
          </Button>
        </div>
      </Modal>

      <Modal
        open={confirmCancel}
        onClose={() => busy == null && setConfirmCancel(false)}
        title="Zum Periodenende kündigen"
        description={`Der Tarif läuft bis ${formatDate(subscription?.current_period_end)} weiter. Danach werden keine Uploads mehr angenommen; Daten bleiben bis zur Löschfrist erhalten.`}
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={() => setConfirmCancel(false)} disabled={busy != null}>
            Abbrechen
          </Button>
          <Button variant="danger" className="border border-danger/50" onClick={() => call({ cancel_at_period_end: true }, "cancel")} disabled={busy != null}>
            {busy === "cancel" ? "Wird gespeichert" : "Kündigen"}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
