#!/usr/bin/env node
/**
 * Findet Schnittkandidaten und schreibt einen Schnittplan-ENTWURF.
 *
 *   node werkzeuge/00-kandidaten-finden.mjs <video> <transcript.json> [kompakt|ruhig]
 *
 * WARUM DIE PAUSEN AUS DEM TON KOMMEN, NICHT AUS DEM TRANSKRIPT:
 * Gemessen am 26.09.2026 mit whisper small/de: das Transkript zog eine echte
 * 2,19-Sekunden-Pause auf 0,0 s zusammen und ließ einen Fehlstart ganz weg.
 * Transkriptzeiten taugen für den Wortlaut, nicht für Stille. Pausen kommen
 * deshalb aus `silencedetect`, das Transkript liefert nur den Beleg dazu.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { basename } from "node:path";

const [, , medienPfad, tPfad, gefuehlArg] = process.argv;
if (!medienPfad) { console.error("Aufruf: node werkzeuge/00-kandidaten-finden.mjs <video> [transcript.json] [kompakt|ruhig]"); process.exit(1); }
if (!existsSync(medienPfad)) { console.error(`FEHLER: '${medienPfad}' gibt es nicht.`); process.exit(1); }

const gefuehl = gefuehlArg || "kompakt";
const SCHWELLE = gefuehl === "ruhig" ? 1.00 : 0.50;  // ab hier gilt eine Pause als kürzbar
const REST     = gefuehl === "ruhig" ? 0.45 : 0.25;  // so viel Pause bleibt stehen
const RAND     = 0.06;                               // Sicherheitsabstand zum Sprechen

const dauer = parseFloat(execFileSync("ffprobe", ["-v","error","-show_entries","format=duration","-of","csv=p=0",medienPfad], { encoding: "utf8" }).trim());

// ---- Stille aus dem Ton messen -------------------------------------------
// ffmpeg schreibt die silencedetect-Meldungen auf stderr, nicht auf stdout.
const lauf = spawnSync("ffmpeg", ["-hide_banner","-i",medienPfad,"-af","silencedetect=noise=-40dB:d=0.30","-f","null","-"],
  { encoding: "utf8", maxBuffer: 1 << 24 });
const log = (lauf.stderr || "") + (lauf.stdout || "");
if (!log.includes("silence_") && !log.includes("Duration")) { console.error("FEHLER: ffmpeg lieferte keine auswertbare Ausgabe."); process.exit(1); }
const stillen = []; let offen = null;
for (const m of log.matchAll(/silence_(start|end): ([0-9.]+)/g)) {
  if (m[1] === "start") offen = parseFloat(m[2]);
  else if (offen !== null) { stillen.push({ start: offen, ende: parseFloat(m[2]) }); offen = null; }
}
if (offen !== null) stillen.push({ start: offen, ende: dauer });
for (const s of stillen) s.laenge = +(s.ende - s.start).toFixed(3);

// ---- Transkript nur als Beleg --------------------------------------------
let woerter = [];
if (tPfad && existsSync(tPfad)) woerter = JSON.parse(readFileSync(tPfad, "utf8"));
const wortBei = (t) => { let b = null, d = 1e9;
  for (const w of woerter) { const x = Math.min(Math.abs(w.start - t), Math.abs(w.end - t)); if (x < d) { d = x; b = w; } }
  return b && d < 2.5 ? b.text : null; };

// ---- Kandidaten ----------------------------------------------------------
const entfernen = [], zurPruefung = [];

// Fehlstart-Verdacht: nur wenig Sprache, dann gleich eine deutliche Pause.
const spracheBis = stillen.length ? stillen[0].start : dauer;
if (stillen.length && spracheBis < 3.0 && stillen[0].laenge > 0.7) {
  zurPruefung.push({ zeit: 0, bereich: [0, +stillen[0].ende.toFixed(3)],
    frage: `Die ersten ${spracheBis.toFixed(2)}s Sprache werden von einer ${stillen[0].laenge}s-Pause abgeschlossen. Das sieht nach einem Fehlstart aus, der danach neu begonnen wird. Anhören: soll 0–${stillen[0].ende.toFixed(2)}s weg?`,
    vorschlag: "anhören — nicht automatisch geschnitten",
    hinweis: "Whisper zieht Fehlstarts oft im Transkript zusammen. Verlass dich hier auf das Ohr." });
}

for (const s of stillen) {
  // Stille am Anfang und Ende immer knapp trimmen
  if (s.start < 0.15) { if (s.ende - RAND > 0.05) entfernen.push({ start: 0, ende: +(s.ende - RAND).toFixed(3), grund: "Stille am Anfang", beleg: "silencedetect", unsicherheit: "keine" }); continue; }
  if (s.ende > dauer - 0.15) { entfernen.push({ start: +(s.start + RAND).toFixed(3), ende: +dauer.toFixed(3), grund: "Stille am Ende", beleg: "silencedetect", unsicherheit: "keine" }); continue; }
  if (s.laenge <= SCHWELLE) continue;

  const a = wortBei(s.start), b = wortBei(s.ende);
  const kuerzenBis = s.ende - RAND - REST;
  if (kuerzenBis > s.start + RAND + 0.05) {
    entfernen.push({ start: +(s.start + RAND).toFixed(3), ende: +kuerzenBis.toFixed(3),
      grund: `Pause von ${s.laenge}s auf ${REST}s gekürzt`,
      beleg: a && b ? `zwischen "${a}" und "${b}" (silencedetect ${s.start.toFixed(2)}–${s.ende.toFixed(2)}s)` : `silencedetect ${s.start.toFixed(2)}–${s.ende.toFixed(2)}s`,
      unsicherheit: s.laenge > 1.8 ? "gering" : "keine" });
  }
  if (s.laenge > 1.5) zurPruefung.push({ zeit: +s.start.toFixed(2),
    frage: `Pause von ${s.laenge}s${a && b ? ` zwischen "${a}" und "${b}"` : ""}. Betonungspause oder Versehen?`,
    vorschlag: s.laenge > 3 ? "kürzen" : "ansehen" });
}

entfernen.sort((x, y) => x.start - y.start);
const behalten = []; let cursor = 0;
for (const e of entfernen) { if (e.start > cursor + 0.05) behalten.push({ start: +cursor.toFixed(3), ende: +e.start.toFixed(3), grund: "Sprechinhalt", unsicherheit: "keine" }); cursor = Math.max(cursor, e.ende); }
if (dauer > cursor + 0.05) behalten.push({ start: +cursor.toFixed(3), ende: +dauer.toFixed(3), grund: "Sprechinhalt", unsicherheit: "keine" });

const name = basename(medienPfad).replace(/\.[^.]+$/, "");
mkdirSync("schnittplaene", { recursive: true });
const ziel = `schnittplaene/${name}.entwurf.json`;
writeFileSync(ziel, JSON.stringify({
  quelle: medienPfad, transkript: tPfad ?? null, schnittgefuehl: gefuehl,
  erstelltAm: new Date().toISOString().slice(0, 10),
  hinweis: "ENTWURF. Pausen stammen aus silencedetect (Ton), nicht aus Transkriptzeiten. Jede Grenze vor dem Schneiden an Bild und Ton nachprüfen. Einträge unter zurPruefung sind NICHT geschnitten.",
  behalten, entfernt: entfernen, zurPruefung,
}, null, 2));

const neu = behalten.reduce((s, b) => s + (b.ende - b.start), 0);
console.log(`Medium: ${dauer.toFixed(2)}s   Gefühl: "${gefuehl}"   Pausenschwelle: ${SCHWELLE}s`);
console.log(`\nStille im Ton (${stillen.length}):`);
stillen.forEach(s => console.log(`   ${s.start.toFixed(2)}–${s.ende.toFixed(2)}s  (${s.laenge}s)${s.laenge > SCHWELLE ? "  -> kürzen" : "  -> bleibt"}`));
console.log(`\nEntwurf: ${dauer.toFixed(2)}s  ->  ${neu.toFixed(2)}s  (${((1 - neu / dauer) * 100).toFixed(0)}% kürzer, ${behalten.length} Bereiche)`);
if (zurPruefung.length) { console.log(`\nZur Prüfung (NICHT geschnitten):`); zurPruefung.forEach(p => console.log(`   ${String(p.zeit).padStart(6)}s  ${p.frage}`)); }
console.log(`\nGeschrieben: ${ziel}`);
