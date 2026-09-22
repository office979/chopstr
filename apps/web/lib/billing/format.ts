import type { Plan, Subscription, SubscriptionStatus, UsagePeriod } from "@/lib/repo/types";

/* Anzeige und Rechnen für die Abrechnung nach Stunden (PHASE4.md, Abschnitt 5). Keine Server-Abhängigkeiten. */

/* DACH-Format: „29 €“, „7,50 €“ */
export function formatEur(value: number): string {
  const whole = Number.isInteger(value);
  return `${value.toLocaleString("de-AT", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: 2 })} €`;
}

export function formatHoursLong(minutes: number): string {
  const h = minutes / 60;
  return `${h.toLocaleString("de-AT", { maximumFractionDigits: 1 })} h`;
}

export const STATUS_LABELS: Record<SubscriptionStatus, string> = {
  trialing: "Testphase",
  active: "Aktiv",
  past_due: "Zahlung überfällig",
  canceled: "Gekündigt",
  paused: "Pausiert",
};

/* Mehrverbrauch pro angefangener Stunde (Spiegel von workers/chopstr_worker/usage.py overage_eur) */
export function overageEur(overageMinutes: number, eurPerHour: number): number {
  if (overageMinutes <= 0) return 0;
  return Math.round(Math.ceil(overageMinutes / 60 - 1e-9) * eurPerHour * 100) / 100;
}

export interface UsageSummary {
  used_minutes: number;
  included_minutes: number;
  ratio: number;
  overage_minutes: number;
  overage_eur: number;
  /* linear auf das Monatsende hochgerechnet */
  forecast_minutes: number;
  forecast_overage_eur: number;
  days_elapsed: number;
  days_total: number;
}

/* Prognose: linear vom bisherigen Verbrauch auf das Monatsende (period_end inklusiv) */
export function summarizeUsage(usage: UsagePeriod | null, plan: Plan | null, now = new Date()): UsageSummary {
  const included = usage?.included_minutes ?? (plan ? plan.included_hours * 60 : 0);
  const used = usage?.used_source_minutes ?? 0;
  const start = usage ? Date.parse(`${usage.period_start}T00:00:00Z`) : Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1);
  const endExclusive = usage ? Date.parse(`${usage.period_end}T00:00:00Z`) + 86_400_000 : Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1);
  const daysTotal = Math.max(1, Math.round((endExclusive - start) / 86_400_000));
  const elapsed = Math.min(daysTotal, Math.max(1, Math.ceil((now.getTime() - start) / 86_400_000)));
  const forecast = elapsed >= daysTotal ? used : (used / elapsed) * daysTotal;
  const rate = plan?.overage_eur_per_hour ?? 0;
  const overageMinutes = Math.max(0, used - included);
  return {
    used_minutes: used,
    included_minutes: included,
    ratio: included > 0 ? Math.min(1, used / included) : 0,
    overage_minutes: overageMinutes,
    overage_eur: usage?.overage_eur && usage.overage_eur > 0 ? usage.overage_eur : overageEur(overageMinutes, rate),
    forecast_minutes: forecast,
    forecast_overage_eur: overageEur(Math.max(0, forecast - included), rate),
    days_elapsed: elapsed,
    days_total: daysTotal,
  };
}

/* Monatsname aus period_start („September 2026“) */
export function formatPeriod(periodStart: string): string {
  const d = new Date(`${periodStart}T00:00:00Z`);
  return d.toLocaleDateString("de-AT", { month: "long", year: "numeric", timeZone: "UTC" });
}

export function isTrialExpired(sub: Subscription | null): boolean {
  return Boolean(sub && sub.status === "trialing" && sub.trial_ends_at && Date.parse(sub.trial_ends_at) < Date.now());
}

export const PLAN_ORDER = ["starter", "pro", "agency", "sovereign"] as const;
