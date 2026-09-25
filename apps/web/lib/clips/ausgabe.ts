/* Darf diese Clipfassung hinaus?
 *
 * Ein Clip verlässt chopstr auf genau zwei Wegen: jemand lädt ihn herunter, oder er wird
 * veröffentlicht. Bis hierher entschied jeder Weg für sich. Die Download-Route prüfte genau eine
 * Sache, nämlich die Gastfreigabe. Sie prüfte nicht, ob der Clip überhaupt freigegeben ist, ob
 * die Datei noch zeigt, was eingestellt ist, und ob am Inhalt ein schwerer Befund hängt. Die
 * Oberfläche prüfte das alles und sperrte den Knopf, aber der Knopf ist nur ein Knopf: wer die
 * Adresse kennt, kam daran vorbei. Auf der Veröffentlichungsseite war es umgekehrt schlimmer, dort
 * stand eine Bedingung, die nie greifen kann - "der Kandidat ist angenommen" ist genau das, wodurch
 * der Clip überhaupt entsteht.
 *
 * Deshalb steht die Entscheidung jetzt hier, einmal, auf dem Server, und die Regeln kommen aus
 * packages/schema/ausgabe_regeln_v1.json. Dieselbe Datei liest der Worker. Die Oberfläche darf die
 * Antwort weiterhin anzeigen, aber sie entscheidet nicht mehr.
 *
 * Die Prüfung ist bewusst für EINE Fassung gedacht, nicht für "den Clip": derselbe Clip kann heute
 * hinausgehen dürfen und morgen nicht, weil jemand den Text geändert hat. Wer fragt, bekommt die
 * Antwort für das, was in diesem Moment in der Datei steht.
 */

import regelnJson from "../../../../packages/schema/ausgabe_regeln_v1.json";
import type { Pruefstand } from "@/lib/clips/pruefstand";
import type { TechnikBefund } from "@/lib/repo/types";

export type Zweck = "herunterladen" | "veroeffentlichen";

export type AusgabeCode =
  | "verworfen"
  | "clippen_laeuft"
  | "clippen_gescheitert"
  | "datei_fehlt"
  | "inhalt_fehler"
  | "technik_fehler"
  | "datei_veraltet"
  | "gast_offen"
  | "gast_veraltet"
  | "nicht_freigegeben"
  | "vertrag_fehlt"
  | "tarif";

interface Regel {
  code: string;
  sperrt: string[];
  text: string;
  hilfe: string;
  href?: string;
}

const REGELN: Regel[] = (regelnJson as { regeln: Regel[] }).regeln;

export const AUSGABE_REGELN_VERSION: string = (regelnJson as { version: string }).version;

export interface AusgabeGrund {
  code: AusgabeCode;
  /* Was los ist, in einem Satz. */
  text: string;
  /* Was hilft, in einem Satz. */
  hilfe: string;
  href?: string;
}

export interface Ausgabe {
  erlaubt: boolean;
  /* Alle zutreffenden Gründe, wichtigster zuerst. Wer nur einen anzeigen kann, nimmt den ersten. */
  gruende: AusgabeGrund[];
}

/* Der technische Befund an der fertigen Datei kommt aus der Datenbank; geschrieben wird er vom
 * Worker in workers/chopstr_worker/pipeline/ausgabe_pruefung.py. */
export type { TechnikBefund };

export interface AusgabeEingabe {
  stand: Pruefstand;
  /* Die technische Prüfung der fertigen Datei. null heisst: nicht geprüft, etwa weil das Video aus
   * der Zeit vor dieser Prüfung stammt. Das sperrt nichts - eine fehlende Messung ist kein Befund,
   * und alte Videos nachträglich zu sperren wäre eine Behauptung über etwas, das niemand gemessen
   * hat. */
  technik: TechnikBefund[] | null;
  /* Eine Gastfreigabe ist verlangt, aber noch nicht erteilt. */
  gastOffen: boolean;
  /* Es gibt eine Freigabe, aber der Clip wurde danach geändert. */
  gastVeraltet: boolean;
  /* Nur für das Veröffentlichen. Beim Herunterladen spielen sie keine Rolle. */
  vertragUnterschrieben?: boolean;
  tarifDarfPosten?: boolean;
}

function regel(code: AusgabeCode): AusgabeGrund {
  const r = REGELN.find((x) => x.code === code);
  /* Kann nur passieren, wenn jemand einen Code hier einträgt und in der JSON vergisst. Dann ist
   * ein sprechender Fehler besser als ein leerer Sperrgrund an der Oberfläche. */
  if (!r) throw new Error(`Ausgabe-Regel fehlt: ${code}`);
  return { code, text: r.text, hilfe: r.hilfe, ...(r.href ? { href: r.href } : {}) };
}

function gilt(code: AusgabeCode, zweck: Zweck): boolean {
  const r = REGELN.find((x) => x.code === code);
  return Boolean(r?.sperrt.includes(zweck));
}

export function ausgabe(zweck: Zweck, e: AusgabeEingabe): Ausgabe {
  const treffer: AusgabeCode[] = [];
  const s = e.stand;

  if (s.redaktion === "verworfen") treffer.push("verworfen");
  if (s.datei === "wird_erstellt") treffer.push("clippen_laeuft");
  if (s.datei === "fehlgeschlagen") treffer.push("clippen_gescheitert");
  if (s.datei === "keine") treffer.push("datei_fehlt");
  /* Ein schwerer Befund am Sinn: der Clip sagt etwas anderes als der Sprecher. Das ist der einzige
   * inhaltliche Grund, der sperrt. Zügiges Sprechen sperrt nicht - das ist unangenehm, aber wahr. */
  if (s.befunde.some((b) => b.schwere === "fehler" && b.art === "sinn")) treffer.push("inhalt_fehler");
  if (e.technik?.some((t) => t.ergebnis === "fehler")) treffer.push("technik_fehler");
  if (s.datei === "veraltet") treffer.push("datei_veraltet");
  if (e.gastOffen) treffer.push("gast_offen");
  if (e.gastVeraltet) treffer.push("gast_veraltet");
  if (s.redaktion !== "freigegeben" && s.redaktion !== "verworfen") treffer.push("nicht_freigegeben");
  if (e.vertragUnterschrieben === false) treffer.push("vertrag_fehlt");
  if (e.tarifDarfPosten === false) treffer.push("tarif");

  /* In der Reihenfolge der Regeldatei, nicht in der Reihenfolge der Prüfung: dort steht, was
   * zuerst zu tun ist. */
  const gruende = REGELN.filter((r) => treffer.includes(r.code as AusgabeCode) && r.sperrt.includes(zweck)).map((r) =>
    regel(r.code as AusgabeCode),
  );
  return { erlaubt: gruende.length === 0, gruende };
}

/* Der Satz für die Oberfläche und für die Fehlermeldung der Schnittstelle: was los ist und was
 * hilft, zusammen. Zwei getrennte Felder wären an der Sperre zwei Zeilen, und die zweite liest
 * niemand. */
export function ausgabeSatz(g: AusgabeGrund): string {
  return `${g.text} ${g.hilfe}`;
}

/* Gilt eine Regel für einen Zweck? Nur für Tests und für die Oberfläche, die erklären will, warum
 * Herunterladen geht und Posten nicht. */
export const regelGiltFuer = gilt;
