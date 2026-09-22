import "server-only";
import type { Repo } from "@/lib/repo/types";
import type { Plan, Subscription, SubscriptionStatus, UsagePeriod } from "@/lib/repo/types";

/* Kontingent-Gate (PHASE4.md, Abschnitt 5): Stunden Quellmaterial pro Monat.
 *
 * Regel für Mehrverbrauch (ohne eigene Spalte in workspaces):
 *   trialing            → kein Mehrverbrauch, Upload-Token wird bei used >= included verweigert (402)
 *   active              → Mehrverbrauch erlaubt (wird je angefangener Stunde abgerechnet)
 *   past_due, paused,
 *   canceled, kein Abo  → kein Mehrverbrauch
 * Block B (Abrechnung) darf diese Funktion um eine explizite Workspace-Einstellung erweitern. */

export function allowOverage(status: SubscriptionStatus | null | undefined): boolean {
  return status === "active";
}

export interface QuotaState {
  plan: Plan | null;
  subscription: Subscription | null;
  usage: UsagePeriod | null;
  used_minutes: number;
  included_minutes: number;
  allow_overage: boolean;
  /* used >= included und kein Mehrverbrauch: Upload verweigern */
  exhausted: boolean;
  message: string | null;
}

export const QUOTA_EXHAUSTED_MESSAGE = "Stundenkontingent ausgeschöpft";

export async function getQuota(repo: Repo): Promise<QuotaState> {
  const subscription = await repo.getSubscription();
  /* Ohne Abo-Zeile (ältere Workspaces, Seed-Daten): Plan aus workspaces.plan, Mehrverbrauch wie im Test gesperrt */
  const planCode = subscription?.plan_code ?? (await repo.getWorkspace()).plan;
  const plan = planCode ? await repo.getPlan(planCode) : null;
  const usage = await repo.getCurrentUsage();
  const included = usage?.included_minutes ?? (plan ? plan.included_hours * 60 : 0);
  const used = usage?.used_source_minutes ?? 0;
  const overage = allowOverage(subscription?.status);
  const exhausted = !overage && used >= included;
  return {
    plan,
    subscription,
    usage,
    used_minutes: used,
    included_minutes: included,
    allow_overage: overage,
    exhausted,
    message: exhausted
      ? `${QUOTA_EXHAUSTED_MESSAGE}: ${formatHours(used)} von ${formatHours(included)} Stunden in diesem Monat verbraucht.`
      : null,
  };
}

export function formatHours(minutes: number): string {
  return (minutes / 60).toLocaleString("de-AT", { maximumFractionDigits: 1 });
}
