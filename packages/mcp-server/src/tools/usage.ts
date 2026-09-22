/* Kontingent des laufenden Monats. */

import { guarded, type ToolContext } from "./common.js";
import { formatDecimal, textResult, unwrapObject } from "../format.js";
import type { Usage } from "../types.js";

export function describeUsage(usage: Usage): string {
  const used = usage.used_source_minutes ?? null;
  const included = usage.included_minutes ?? null;
  const usedH = used !== null ? used / 60 : null;
  const inclH = included !== null ? included / 60 : null;
  const pct = usedH !== null && inclH ? Math.round((usedH / inclH) * 100) : null;
  const plan = typeof usage.plan === "string" ? usage.plan : usage.plan?.name ?? null;
  return [
    `Kontingent ${usage.period_start ?? "?"} bis ${usage.period_end ?? "?"}${plan ? ` (Plan ${plan})` : ""}:`,
    `Quellmaterial: ${formatDecimal(usedH)} von ${formatDecimal(inclH)} Stunden${pct !== null ? ` (${pct} %)` : ""}`,
    usage.render_count !== undefined ? `Renders: ${usage.render_count}` : null,
    usage.overage_minutes ? `Mehrverbrauch: ${formatDecimal(usage.overage_minutes / 60)} Stunden, ${formatDecimal(usage.overage_eur ?? 0, 2)} €` : null,
    pct !== null && pct >= 100 ? "Das Kontingent ist erschöpft: neue Quellen scheitern mit 402, bis Mehrverbrauch freigeschaltet oder der Plan gewechselt ist." : pct !== null && pct >= 80 ? "Hinweis: über 80 % des Kontingents verbraucht." : null,
  ]
    .filter((l): l is string => Boolean(l))
    .join("\n");
}

export function registerUsageTools({ server, api }: ToolContext): void {
  server.registerTool(
    "get_usage",
    {
      title: "Kontingent anzeigen",
      description: "Zeigt das Stundenkontingent des laufenden Monats: enthaltene und verbrauchte Stunden Quellmaterial, Renders, Mehrverbrauch.",
      inputSchema: {},
      annotations: { readOnlyHint: true, openWorldHint: false },
    },
    async () =>
      guarded(async () => {
        const body = await api.get<unknown>("/usage");
        const usage = unwrapObject<Usage>(body, "usage");
        return textResult(describeUsage(usage), { usage: usage as Record<string, unknown> });
      }),
  );
}
