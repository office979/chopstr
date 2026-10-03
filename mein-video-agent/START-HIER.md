# START HIER — dein Video-Agent

Stand: 26.09.2026 · Alles läuft auf deinem Mac. Nichts wird hochgeladen.

---

## 1. Wo liegt das Projekt

```
/Users/jarvisplatz/Documents/GitHub/chopstr/mein-video-agent
```

---

## 2. Vorschau öffnen (der wichtigste Befehl)

```bash
cd /Users/jarvisplatz/Documents/GitHub/chopstr/mein-video-agent && npm run dev
```

Danach im Browser öffnen: **http://localhost:3002**

Die Vorschau lädt sich selbst neu, sobald sich etwas ändert. Beenden mit `Strg + C`.

Wenn die Vorschau im Hintergrund laufen soll (damit der Agent weiterarbeiten kann):

```bash
cd /Users/jarvisplatz/Documents/GitHub/chopstr/mein-video-agent && npx hyperframes@0.8.77 preview --background
```

Läuft sie? `npx hyperframes@0.8.77 preview --status` · Stoppen: `npx hyperframes@0.8.77 preview --stop`

---

## 3. Die drei Arbeitsbefehle

| Was du willst | Befehl |
|---|---|
| Fehler suchen, bevor gerendert wird | `npm run check` |
| Video erzeugen | `npm run render -- -o mein-video.mp4` |
| Vorschau starten | `npm run dev` |

> Immer `-o dateiname.mp4` angeben. So wird nie ein früherer Export überschrieben.

---

## 4. Installierte Versionen

| Bestandteil | Version | Ort |
|---|---|---|
| HyperFrames CLI | **0.8.77** (festgelegt in `package.json`) | über `npx` |
| Node.js | 25.8.0 | System |
| npm | 11.11.0 | System |
| FFmpeg / ffprobe | 8.0.1 | `/opt/homebrew/bin/` |
| whisper.cpp | 1.9.4 | `/opt/homebrew/bin/whisper-cli` |
| Whisper-Modell | `ggml-small.bin`, mehrsprachig, 465 MB | `~/.cache/hyperframes/whisper/models/` |
| macOS | 26.1, Apple M4 | — |

**Wichtig zur Version:** Die CLI ist bewusst auf 0.8.77 festgenagelt, damit alles reproduzierbar bleibt.
Es gibt bereits 0.8.78. Ein Update erfolgt nur, wenn du es ausdrücklich möchtest.

### Stand der offiziellen Skills

Installiert am 26.09.2026 mit `npx hyperframes@0.8.77 skills update general-video motion-graphics`.
Der Skill-Updater lädt immer den **aktuellen** öffentlichen Stand — er ist nicht an die CLI-Version gebunden.
Quelle: `heygen-com/hyperframes` über skills.sh. Lockdatei: `~/.agents/.skill-lock.json`.

Installiert wurden 12 Skills (Prüfsummen zum Zeitpunkt der Installation):

| Skill | Hash |
|---|---|
| hyperframes (Einstieg) | `a624fd0aa39bdd09` |
| hyperframes-core | `b4d9c7b3d0e5ae75` |
| hyperframes-animation | `9add954e7eff1aa6` |
| hyperframes-audio | `7e9a13aba7143c08` |
| hyperframes-cli | `f006eefddf345fd1` |
| hyperframes-creative | `0803c90800fda4ce` |
| hyperframes-keyframes | `16a7da9819e7e4ab` |
| hyperframes-registry | `4a1a7daf23a9e569` |
| hyperframes-studio | `b063eaa9eb1e4b9b` |
| media-use | `b35de041b87e763d` |
| **general-video** | `36b4d47cf01c451d` |
| **motion-graphics** | `ab9d2e9c205ce1b1` |

Aktuellen Stand jederzeit prüfen: `npx hyperframes@0.8.77 skills check`

Die Skills liegen benutzerweit in `~/.claude/skills/` und `~/.agents/skills/`.
Geprüft: **keine deiner 57 bestehenden Skills wurde verändert oder gelöscht** (0 Dateien geändert, 0 entfernt).
Sicherung des Zustands davor liegt im Sitzungsordner unter `skills-snapshot/skills-vorher.tgz`.

---

## 5. Was heruntergeladen wurde

| Download | Größe | Wann |
|---|---|---|
| whisper.cpp über Homebrew (mit ggml, llama.cpp, sdl2-compat) | ca. 150–250 MB | einmalig, erledigt |
| Whisper-Modell `small` (mehrsprachig, für Deutsch) | 465 MB | einmalig, erledigt |
| HyperFrames CLI + Chrome für das Rendern | wenige hundert MB im npx-Cache | automatisch |

Freier Speicher danach: rund 183 GB. Keine Administratorrechte nötig — alles lief in deinem Benutzerbereich.

---

## 6. Bestandene Prüfungen

Geprüft an einem selbst erzeugten, neutralen 5-Sekunden-Testclip (bewegte Formen + Ton).
Keine fremden Medien, keine privaten Dateien.

| Prüfung | Ergebnis |
|---|---|
| `check` (Lint, Laufzeit, Layout, Bewegung, Kontrast) | bestanden — 0 Fehler, Kontrast 8/8 nach WCAG AA |
| Render nach MP4 | bestanden — `pruefung/einrichtungspruefung-v2.mp4` |
| Auflösung | 1920 × 1080 ✓ |
| Dauer | exakt 5,000 s ✓ |
| Bildrate und Bildanzahl | 30 fps, genau 150 Bilder ✓ |
| Ton vorhanden | AAC, 48 kHz, Stereo ✓ |
| **Bild-Ton-Synchronität** | Bildmarke und Tonbeginn liegen beide exakt bei 2,0 s ✓ |
| Ton davor still | −91 dB von 0,0–1,9 s ✓ |
| Bewegung im Bild | grüne Form an allen drei Messpunkten an der erwarteten Stelle ✓ |
| Textüberlagerung | lesbar, sichtbar, korrekt eingeblendet ✓ |
| Vorschau (Studio) | öffnet sich, zeigt Komposition und Timeline ✓ |
| **Lokale Transkription Deutsch** | `ok: true`, 21 Wörter mit echten Zeitstempeln, monoton steigend, alle innerhalb der Aufnahme ✓ |

Ein währenddessen gefundener Fehler wurde behoben und der Test danach vollständig wiederholt:
Der erste Testclip zeigte die bewegten Formen nicht, weil der FFmpeg-Filter `drawbox` seine
Positionsangaben nicht pro Bild neu berechnet. Umgestellt auf `overlay` — danach korrekt.
Der Fehler lag am Testclip, nicht an HyperFrames.

### Prüfdateien

```
pruefung/einrichtungspruefung-v1.mp4   erster Render (mit dem Formen-Fehler, zum Vergleich behalten)
pruefung/einrichtungspruefung-v2.mp4   Render nach der Korrektur — der gültige
pruefung/bild-v2-t3.0s.png             Einzelbild zur Sichtprüfung
pruefung/index.blank-original.html     das unveränderte leere Beispiel von HyperFrames
pruefung/transkription/                Sprachprobe und ihr Transkript
assets/testclip.mp4                    der neutrale Testclip
```

---

## 7. Offene Punkte

1. **Transkription an deiner echten Stimme prüfen.**
   Geprüft wurde bisher mit einer künstlichen deutschen Systemstimme. Die technische Kette
   steht damit nachweislich. Echte Sprache klingt aber anders: Versprecher, Dialekt,
   Hintergrundgeräusche. **Dafür brauche ich eine kurze Aufnahme von dir** (30–90 Sekunden reichen).

2. **Telemetrie ist eingeschaltet.**
   HyperFrames sendet anonyme Nutzungsdaten an HeyGen. Laut Anbieter *keine* Dateipfade,
   Projektnamen oder Videoinhalte. Ich habe daran nichts geändert.
   Abschalten, falls gewünscht: `npx hyperframes@0.8.77 telemetry disable`

3. **Dein FFmpeg kann keinen Text ins Bild schreiben** (ohne `freetype` gebaut, `drawtext` fehlt).
   Für diesen Agenten ist das kein Problem — Text und Grafik kommen von HyperFrames.
   Nur reine FFmpeg-Textbefehle funktionieren nicht.

4. **Docker fehlt.** Wird nur für Cloud-Rendern gebraucht, nicht für die lokale Arbeit.

---

## 8. Was an das KI-Modell geht

Damit du es weißt: *lokale* Transkription heißt, dass die **Spracherkennung** auf deinem Mac läuft —
nicht, dass der Inhalt privat im Chat bleibt.

Sobald ich an einem Video arbeite, sehe ich:
- den **Transkripttext** deiner Aufnahme (um Schnittstellen zu finden),
- einzelne **Standbilder** aus dem Video (um Bildfehler zu prüfen).

Beides geht als Teil des Gesprächs an das Modell. Die Videodatei selbst nicht.
Bei vertraulichem Material sag mir vorher Bescheid.

Bisher übergeben: nur selbst erzeugte Testbilder und der selbst diktierte Probesatz.
