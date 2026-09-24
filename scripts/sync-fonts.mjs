/* Untertitel-Schriften aus workers/fonts nach apps/web/public/fonts spiegeln.
 *
 * Die Dateien liegen beim Worker, denn dort werden sie gebraucht: libass brennt die Untertitel ein.
 * Die Oberflaeche braucht dieselben Dateien, um im Editor zu zeigen, wie der Clip aussehen wird -
 * und Next kann nur aus public/ ausliefern. Statt die Dateien zweimal im Repo zu halten, kopiert
 * dieses Skript sie. Das Ziel steht in .gitignore.
 *
 *   node scripts/sync-fonts.mjs
 */
import { readFileSync, mkdirSync, copyFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const hier = path.dirname(fileURLToPath(import.meta.url));
const wurzel = path.resolve(hier, "..");
const quelle = path.join(wurzel, "workers", "fonts");
const ziel = path.join(wurzel, "apps", "web", "public", "fonts");
const liste = JSON.parse(readFileSync(path.join(wurzel, "packages", "design", "caption_fonts.json"), "utf8"));

mkdirSync(ziel, { recursive: true });
const fehlend = [];
let kopiert = 0;
for (const schrift of liste.schriften) {
  const von = path.join(quelle, schrift.datei);
  if (!existsSync(von)) {
    fehlend.push(schrift);
    continue;
  }
  copyFileSync(von, path.join(ziel, schrift.datei));
  kopiert += 1;
}
console.log(`${kopiert} von ${liste.schriften.length} Schriften gespiegelt nach ${path.relative(wurzel, ziel)}`);
if (fehlend.length) {
  console.log("\nDiese Dateien fehlen in workers/fonts. Ohne sie faellt der Render auf Inter zurueck");
  console.log("und der Editor sagt es in der Vorschau:");
  for (const s of fehlend) console.log(`  ${s.datei.padEnd(30)} ${s.id} — ${s.quelle}`);
}
