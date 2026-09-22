import "server-only";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

/* Rechtstexte (PHASE4.md, Abschnitt 6) aus docs/rechtliches/*.md des Monorepos, gelesen beim Laden des Moduls
 * (Build- beziehungsweise Serverstart). Fehlt eine Datei, liefert `loadLegalDoc` null und die Seite zeigt
 * einen Hinweis statt eines leeren Vertrags. */

export type LegalDocKey = "avv" | "toms" | "subprozessoren";

export const DPA_VERSION = process.env.DPA_VERSION ?? "2026-09";

export interface LegalDoc {
  key: LegalDocKey;
  version: string;
  status: string;
  /* Markdown ohne Frontmatter */
  markdown: string;
  file: string;
}

const FILES: Record<LegalDocKey, string> = {
  avv: `avv-${DPA_VERSION}.md`,
  toms: `toms-${DPA_VERSION}.md`,
  subprozessoren: `subprozessoren-${DPA_VERSION}.md`,
};

/* Kandidaten für den Ordner: relativ zur App (apps/web → ../../docs) und relativ zum Monorepo-Root */
function docsDirs(): string[] {
  const cwd = process.cwd();
  return [path.resolve(cwd, "../../docs/rechtliches"), path.resolve(cwd, "docs/rechtliches"), path.resolve(cwd, "../docs/rechtliches")];
}

function parseFrontmatter(raw: string): { meta: Record<string, string>; body: string } {
  const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!m) return { meta: {}, body: raw };
  const meta: Record<string, string> = {};
  for (const line of m[1].split(/\r?\n/)) {
    const idx = line.indexOf(":");
    if (idx > 0) meta[line.slice(0, idx).trim()] = line.slice(idx + 1).trim().replace(/^"|"$/g, "");
  }
  return { meta, body: raw.slice(m[0].length) };
}

function read(key: LegalDocKey): LegalDoc | null {
  for (const dir of docsDirs()) {
    const file = path.join(dir, FILES[key]);
    if (!existsSync(file)) continue;
    const { meta, body } = parseFrontmatter(readFileSync(file, "utf8"));
    return { key, version: meta.version ?? DPA_VERSION, status: meta.status ?? "Vorlage, juristisch zu prüfen", markdown: body, file };
  }
  return null;
}

const cache: Partial<Record<LegalDocKey, LegalDoc | null>> = {
  avv: read("avv"),
  toms: read("toms"),
  subprozessoren: read("subprozessoren"),
};

export function loadLegalDoc(key: LegalDocKey): LegalDoc | null {
  if (!(key in cache)) cache[key] = read(key);
  return cache[key] ?? null;
}

export interface DpaFill {
  company: string | null;
  representative: string | null;
  address: string | null;
  retention_days: number | null;
  render_retention_days: number | null;
  accepted_at: string | null;
  ip: string | null;
  version: string;
}

/* Platzhalter aus dem Workspace befüllen; fehlende Werte bleiben als Platzhalter sichtbar */
export function fillPlaceholders(markdown: string, fill: DpaFill): string {
  const or = (v: string | null | undefined, ph: string) => (v && v.trim() ? v.trim() : ph);
  let out = markdown;
  out = out.replace(/\[Firma des Kunden\]/g, or(fill.company, "[Firma des Kunden]"));
  out = out.replace(/\[Vertreter\]/g, or(fill.representative, "[Vertreter]"));
  out = out.replace(/\[Aufbewahrung in Tagen des Workspace, Standard 30\]/g, fill.retention_days != null ? String(fill.retention_days) : "[Aufbewahrung in Tagen des Workspace, Standard 30]");
  out = out.replace(/Renderings: 90 Tage/g, fill.render_retention_days != null ? `Renderings: ${fill.render_retention_days} Tage` : "Renderings: 90 Tage");
  out = out.replace(/\[Datum\]/g, fill.accepted_at ? new Date(fill.accepted_at).toLocaleString("de-AT", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "[Datum]");
  out = out.replace(/IP \[Adresse\]/g, `IP ${or(fill.ip, "[Adresse]")}`);
  out = out.replace(/\[Version\]/g, fill.version);
  /* Adresse des Verantwortlichen: erste [Adresse] nach der Firma */
  if (fill.address) out = out.replace(/\*\*(.+?)\*\*, \[Adresse\], vertreten/, `**$1**, ${fill.address}, vertreten`);
  return out;
}

/* Subprozessor-Liste je Tarif: nur der Abschnitt „## Tarif Standard“ oder „## Tarif Sovereign“ */
export function filterSubprocessors(markdown: string, tier: "standard" | "sovereign" | null): string {
  if (!tier) return markdown;
  const wanted = tier === "sovereign" ? "## Tarif Sovereign" : "## Tarif Standard";
  const sections = markdown.split(/(?=^## )/m);
  const head = sections.filter((s) => !s.startsWith("## "));
  const kept = sections.filter((s) => s.startsWith(wanted));
  return [...head, ...kept].join("");
}
