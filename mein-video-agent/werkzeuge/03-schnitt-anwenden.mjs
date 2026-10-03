#!/usr/bin/env node
/**
 * Wendet einen Schnittplan an.
 *
 *   node werkzeuge/03-schnitt-anwenden.mjs schnittplaene/tipp1.json [ausgabename]
 *
 * Erzeugt drei Dinge:
 *   schnitte/<name>.geschnitten.mp4        Bild und Ton synchron, EINE Tonspur
 *   schnitte/<name>.zeitzuordnung.json     Quellzeit  ->  Schnittzeit, plus Nahtstellen
 *   schnitte/<name>.transcript-schnitt.json  Transkript auf der NEUEN Zeitachse
 *
 * Originale werden nur gelesen. Vorhandene Ausgaben werden nie überschrieben.
 */
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { basename } from "node:path";

const planPfad = process.argv[2];
if (!planPfad) { console.error("Aufruf: node werkzeuge/03-schnitt-anwenden.mjs <schnittplan.json> [name]"); process.exit(1); }
if (!existsSync(planPfad)) { console.error(`FEHLER: '${planPfad}' gibt es nicht.`); process.exit(1); }

const plan = JSON.parse(readFileSync(planPfad, "utf8"));
const name = process.argv[3] || basename(planPfad).replace(/\.json$/, "");
mkdirSync("schnitte", { recursive: true });

const ziel = `schnitte/${name}.geschnitten.mp4`;
const zuordnungPfad = `schnitte/${name}.zeitzuordnung.json`;
const transkriptZiel = `schnitte/${name}.transcript-grob.json`;
for (const f of [ziel, zuordnungPfad, transkriptZiel])
  if (existsSync(f)) { console.error(`FEHLER: '${f}' existiert schon. Anderen Namen wählen — es wird nichts überschrieben.`); process.exit(1); }

const quelle = plan.quelle;
if (!quelle || !existsSync(quelle)) { console.error(`FEHLER: Quelle '${quelle}' aus dem Schnittplan fehlt.`); process.exit(1); }

// ---- Bereiche prüfen ------------------------------------------------------
let behalten = plan.behalten;
if (!Array.isArray(behalten) || behalten.length === 0) { console.error("FEHLER: Der Schnittplan hat kein 'behalten'."); process.exit(1); }
behalten = [...behalten].sort((a, b) => a.start - b.start);

const ffprobe = (args) => execFileSync("ffprobe", args, { encoding: "utf8" }).trim();
const dauerQuelle = parseFloat(ffprobe(["-v","error","-show_entries","format=duration","-of","csv=p=0",quelle]));
const tonspuren = ffprobe(["-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",quelle]).split("\n").filter(Boolean).length;
if (tonspuren === 0) { console.error("FEHLER: Die Quelle hat keinen Ton."); process.exit(1); }

let vorigesEnde = -1;
for (const [i, b] of behalten.entries()) {
  if (typeof b.start !== "number" || typeof b.ende !== "number") { console.error(`FEHLER: Bereich ${i} hat keine Zahlen für start/ende.`); process.exit(1); }
  if (b.ende <= b.start) { console.error(`FEHLER: Bereich ${i}: Ende (${b.ende}) liegt nicht nach Start (${b.start}).`); process.exit(1); }
  if (b.start < 0 || b.ende > dauerQuelle + 0.05) { console.error(`FEHLER: Bereich ${i} (${b.start}–${b.ende}s) liegt außerhalb der Quelle (0–${dauerQuelle.toFixed(2)}s).`); process.exit(1); }
  if (b.start < vorigesEnde - 0.001) { console.error(`FEHLER: Bereich ${i} überlappt den vorherigen. Bereiche dürfen sich nicht überschneiden.`); process.exit(1); }
  vorigesEnde = b.ende;
}

// ---- Zeitzuordnung aufbauen ----------------------------------------------
const abschnitte = []; const nahtstellen = []; let schnittZeit = 0;
for (const [i, b] of behalten.entries()) {
  const laenge = b.ende - b.start;
  abschnitte.push({
    nummer: i, quelleStart: +b.start.toFixed(3), quelleEnde: +b.ende.toFixed(3),
    schnittStart: +schnittZeit.toFixed(3), schnittEnde: +(schnittZeit + laenge).toFixed(3),
    grund: b.grund ?? null, unsicherheit: b.unsicherheit ?? "keine",
  });
  schnittZeit += laenge;
  if (i < behalten.length - 1) nahtstellen.push(+schnittZeit.toFixed(3));
}
const gesamt = schnittZeit;

// ---- Schneiden: trim + atrim + concat ist framegenau und hält Bild/Ton zusammen
const filter = behalten.map((b, i) =>
  `[0:v]trim=start=${b.start}:end=${b.ende},setpts=PTS-STARTPTS[v${i}];` +
  `[0:a]atrim=start=${b.start}:end=${b.ende},asetpts=PTS-STARTPTS[a${i}]`
).join(";") + ";" +
  behalten.map((_, i) => `[v${i}][a${i}]`).join("") +
  `concat=n=${behalten.length}:v=1:a=1[v][a]`;

console.log(`Quelle:    ${quelle}  (${dauerQuelle.toFixed(2)}s)`);
console.log(`Behalten:  ${behalten.length} Bereich(e)  ->  ${gesamt.toFixed(2)}s`);
console.log(`Entfernt:  ${(dauerQuelle - gesamt).toFixed(2)}s (${((1 - gesamt / dauerQuelle) * 100).toFixed(0)}%)`);
console.log("Schneide …");

execFileSync("ffmpeg", ["-hide_banner","-loglevel","error","-y","-i",quelle,
  "-filter_complex",filter,"-map","[v]","-map","[a]",
  "-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p",
  "-c:a","aac","-b:a","192k","-ar","48000","-movflags","+faststart", ziel], { stdio: "inherit" });

// ---- Ergebnis nachmessen --------------------------------------------------
const istDauer = parseFloat(ffprobe(["-v","error","-show_entries","format=duration","-of","csv=p=0",ziel]));
const istTonspuren = ffprobe(["-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",ziel]).split("\n").filter(Boolean).length;
const abweichung = Math.abs(istDauer - gesamt);
if (istTonspuren !== 1) { console.error(`FEHLER: Die Ausgabe hat ${istTonspuren} Tonspuren statt genau einer.`); process.exit(1); }
if (abweichung > 0.15) { console.error(`FEHLER: Dauer weicht ab — geplant ${gesamt.toFixed(2)}s, tatsächlich ${istDauer.toFixed(2)}s.`); process.exit(1); }

writeFileSync(zuordnungPfad, JSON.stringify({
  geschnitteneDatei: ziel, quelle,
  offsetZumOriginal: plan.quelleOffsetZumOriginal ?? 0,
  originalaufnahme: plan.originalaufnahme ?? null,
  gesamtdauer: +istDauer.toFixed(3), geplanteDauer: +gesamt.toFixed(3),
  abschnitte, nahtstellen,
  hinweis: "schnittStart/schnittEnde gelten für die geschnittene Datei. Untertitel und B-Roll richten sich NUR danach. Originalzeit = quelleStart + offsetZumOriginal.",
}, null, 2));

// ---- Transkript auf die neue Zeitachse umrechnen --------------------------
const transkriptQuelle = plan.transkript ?? quelle.replace(/\.[^.]+$/, ".transcript.json");
if (existsSync(transkriptQuelle)) {
  const woerter = JSON.parse(readFileSync(transkriptQuelle, "utf8"));
  const neu = []; let weg = 0;
  for (const w of woerter) {
    // Ein Wort zählt zu dem Abschnitt, in dem seine Mitte liegt — so landen
    // Wörter direkt an einer Naht nicht doppelt und nicht nirgends.
    const mitte = (w.start + w.end) / 2;
    const a = abschnitte.find((x) => mitte >= x.quelleStart && mitte < x.quelleEnde);
    if (!a) { weg++; continue; }
    const versatz = a.schnittStart - a.quelleStart;
    neu.push({ id: `w${neu.length}`, text: w.text,
      start: +Math.max(a.schnittStart, w.start + versatz).toFixed(3),
      end:   +Math.min(a.schnittEnde,  w.end   + versatz).toFixed(3),
      quelleStart: w.start, quelleEnde: w.end });
  }
  writeFileSync(transkriptZiel, JSON.stringify(neu, null, 2));
  console.log(`Transkript grob umgerechnet: ${neu.length} Wörter übernommen, ${weg} weggefallen.`);
  console.log(`  ACHTUNG: Diese Umrechnung taugt NICHT für Untertitel.`);
  console.log(`  Gemessen am 26.09.2026: Whisper-Zeiten passen nicht immer zum Ton, dadurch fallen`);
  console.log(`  beim Umrechnen Wörter mitten aus Sätzen heraus. Für Untertitel IMMER die`);
  console.log(`  geschnittene Datei neu transkribieren:`);
  console.log(`     ./werkzeuge/02-transkribieren.sh ${ziel} de small`);
} else {
  console.log(`Hinweis: kein Quelltranskript unter '${transkriptQuelle}'.`);
}
console.log(`\nNaechster Schritt fuer Untertitel (Pflicht, nicht optional):`);
console.log(`   ./werkzeuge/02-transkribieren.sh ${ziel} de small`);

console.log(`\nFertig:`);
console.log(`  Video:         ${ziel}  (${istDauer.toFixed(2)}s, 1 Tonspur)`);
console.log(`  Zeitzuordnung: ${zuordnungPfad}`);
console.log(`  Nahtstellen auf der Schnitt-Timeline: ${nahtstellen.map((n) => n.toFixed(2) + "s").join(", ") || "keine"}`);
console.log(`\n  -> Jede Nahtstelle muss der Qualitätsprüfer einzeln kontrollieren.`);
