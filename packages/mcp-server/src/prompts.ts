/* Prompts: Anleitung für eine Review-Sitzung und die Hook-Regeln (hooks_v1) als Vorlage. */

import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

/* Spiegel von packages/prompts/hooks_v1.md (Version 1). Bei einer neuen Prompt-Version hier nachziehen; ein Test vergleicht beide. */
export const HOOKS_V1_RULES = `Schreibe 5 Hook-Varianten für diesen Clip: je eine Variante der Muster identity_call, contrarian,
open_loop, results_first, mistake_warning. Zu jeder Variante: spoken (max. 12 Wörter, gesprochen) und
onscreen (max. 9 Wörter, Text im Bild).

Regeln:
- Anrede: {address}. Land: {country}. Plattform: {platform}. Anrede nie mischen.
- Jede Behauptung muss durch den Clip gedeckt sein. Keine Zahl, die nicht im Clip vorkommt.
- Kein Superlativ, kein Gesundheits-, Rendite- oder Heilsversprechen, das der Clip nicht wörtlich enthält.
- Keine Floskeln, keine Gedankenstriche, kein Hype, keine Emojis. Konkret statt allgemein.
- Hauptsatz vor Nebensatz, Kernwort vorn: „40.000 € habe ich verloren, weil …“ statt „Weil ich …“.
- Regionale Begriffe des Sprechers nicht ins Standarddeutsch umschreiben: {protected_terms}
- Abgenutzte Muster vermeiden: „Du glaubst nicht …“, „Wenn ich das früher gewusst hätte …“,
  „Niemand spricht darüber …“, „Das hat mein Leben verändert“, „Warte bis zum Ende“.
- LinkedIn: erste Zeile 1 bis 8 Wörter als klares Statement, Belege vor Behauptung.

CLIP:
{clip_text}`;

export function renderHookBrief(args: { address?: string; country?: string; platform?: string; protected_terms?: string; clip_text?: string }): string {
  const fill = (key: string, fallback: string) => {
    const value = (args as Record<string, string | undefined>)[key];
    return value && value.trim() ? value.trim() : fallback;
  };
  return HOOKS_V1_RULES.replace("{address}", fill("address", "du"))
    .replace("{country}", fill("country", "DE"))
    .replace("{platform}", fill("platform", "tiktok"))
    .replace("{protected_terms}", fill("protected_terms", "(keine)"))
    .replace("{clip_text}", fill("clip_text", "(Clip-Text mit get_clip oder get_transcript laden und hier einsetzen)"));
}

export function renderReviewSession(sourceId: string | undefined, focus: string | undefined): string {
  const target = sourceId ? `der Quelle ${sourceId}` : "einer Quelle (ID mit list_sources ermitteln)";
  return `Du prüfst die Clip-Kandidaten ${target} als Senior-Redaktion für den DACH-Raum. Die KI hat vorgeschlagen und bewertet, du entscheidest wie ein Mensch, der die Verantwortung trägt. Nichts wird ohne ausdrückliche Bestätigung des Nutzers angenommen, abgelehnt oder veröffentlicht.

Vorgehen:
1. list_candidates mit gate_passed: true und verdict: open aufrufen. Kandidaten mit verletzten Gates danach getrennt ansehen (gate_passed: false); sie sind keine Kandidaten für die Annahme, aber Hinweise für revise_candidate.
2. Für jeden Kandidaten den Clip-Text (rubric.text) lesen und bei Unklarheit das Transkript um den Kandidaten herum mit get_transcript (start_s minus 30 s, end_s plus 30 s) prüfen.
3. Je Kandidat diese Regeln anwenden:
   - Eigenständigkeit: Der Clip muss ohne Vorwissen verständlich sein. Offene Verweise („wie gesagt“, „das da“, „er“ ohne Bezug) disqualifizieren, außer eine Titelkarte mit höchstens 8 Wörtern löst sie auf (revise_candidate mit title_card).
   - Sinntreue: Der Clip darf die Aussage des Originals nicht verschieben. Story-Graph-Hinweise ernst nehmen: relativiert ein späterer Satz die Aussage, dann verlängern (revise_candidate) oder ablehnen, nie verkürzen, damit es knackiger wirkt.
   - Keine Zahl ohne Beleg: Jede Zahl, jeder Superlativ, jedes Versprechen im Clip, im Hook oder im Post-Text muss wörtlich im Clip-Text vorkommen. Belege in rubric.scores.*.evidence prüfen, nicht glauben.
   - Humor ist immer Mensch: Kandidaten mit risk_flags humor oder is_humor werden nie allein von dir angenommen. Ironie, Zuspitzung und Witz beurteilt der Nutzer; du legst sie mit Begründung vor.
   - Sensible Themen (sensitive_topic) und Werbung (ad): auf Kennzeichnung und Kontext hinweisen, Entscheidung beim Nutzer.
   - Heuristik-Kandidaten (risk_flag heuristic_only) sind ohne Sprachmodell entstanden: Scores nicht als Urteil werten.
4. Ergebnis als kurze Liste: je Kandidat ID, Zeitfenster, Empfehlung (annehmen, anpassen, ablehnen, Rückfrage), ein Satz Begründung mit Beleg aus dem Text.${focus ? `\n   Schwerpunkt dieser Sitzung: ${focus}` : ""}
5. Erst nach Bestätigung des Nutzers accept_candidate oder reject_candidate mit confirm: true aufrufen. Beim Ablehnen ist ein kurzer, ehrlicher Grund Pflicht (Lernsignal). Keine Sammelaktionen ohne Einzelfreigabe.

Ton: sachlich, konkret, deutsch. Keine Gedankenstriche, keine Emojis, keine Floskeln.`;
}

export function registerPrompts(server: McpServer): void {
  server.registerPrompt(
    "review_session",
    {
      title: "Review-Sitzung",
      description: "Anleitung, die Kandidaten einer Quelle nach den chopstr-Regeln zu prüfen: Eigenständigkeit, Sinntreue, keine Zahl ohne Beleg, Humor immer Mensch.",
      argsSchema: {
        source_id: z.string().optional().describe("ID der Quelle"),
        focus: z.string().optional().describe("Optionaler Schwerpunkt, zum Beispiel LinkedIn oder eine Zielgruppe"),
      },
    },
    ({ source_id, focus }) => ({
      description: "Review der Kandidaten nach den chopstr-Regeln",
      messages: [{ role: "user", content: { type: "text", text: renderReviewSession(source_id, focus) } }],
    }),
  );

  server.registerPrompt(
    "hook_brief",
    {
      title: "Hook-Briefing (hooks_v1)",
      description: "Die Regeln aus packages/prompts/hooks_v1.md als Vorlage: fünf Hook-Varianten nach Muster, Wortlimits 12/9, keine Zahl ohne Beleg.",
      argsSchema: {
        address: z.string().optional().describe("Anrede: du oder sie"),
        country: z.string().optional().describe("Land: DE, AT oder CH"),
        platform: z.string().optional().describe("Zielplattform: tiktok, reels, shorts oder linkedin"),
        protected_terms: z.string().optional().describe("Regionale Begriffe, kommagetrennt, die nicht umgeschrieben werden dürfen"),
        clip_text: z.string().optional().describe("Wörtlicher Clip-Text"),
      },
    },
    (args) => ({
      description: "Hook-Regeln hooks_v1",
      messages: [{ role: "user", content: { type: "text", text: renderHookBrief(args) } }],
    }),
  );
}
