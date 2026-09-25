/* Die Sperrgründe für das Veröffentlichen, in der Form, die die Schnittstelle schon kennt.
 *
 * Gerechnet wird hier nichts mehr. Die Regeln stehen in packages/schema/ausgabe_regeln_v1.json und
 * werden von lib/clips/ausgabe.ts ausgewertet, für Download und Veröffentlichung gemeinsam. Dass
 * es beides gab, war der Fehler: die alte Fassung dieser Datei prüfte fünf Dinge, von denen eines
 * gar nicht prüfbar war.
 *
 * `candidate.human_verdict === "accepted"` stand hier als Bedingung für das Posten. Das Annehmen
 * eines Kandidaten ist aber genau der Vorgang, durch den der Clip überhaupt entsteht. Ein Clip
 * ohne angenommenen Kandidaten kann es nicht geben, also war diese Bedingung immer erfüllt und hat
 * nie etwas verhindert. Sie sah nach einer Prüfung aus und war keine. An ihrer Stelle steht jetzt
 * die Frage, die wirklich offen ist: hat ein Mensch diesen Clip freigegeben?
 */

import { ausgabeSatz, type Ausgabe, type AusgabeCode } from "@/lib/clips/ausgabe";

export interface GateReason {
  code: AusgabeCode;
  message: string;
  href?: string;
}

export function gateReasons(a: Ausgabe): GateReason[] {
  return a.gruende.map((g) => ({ code: g.code, message: ausgabeSatz(g), ...(g.href ? { href: g.href } : {}) }));
}
