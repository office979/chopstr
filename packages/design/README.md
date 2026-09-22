# @chopstr/design · Lichtbruch

Design-System für App, Website und Marketing von chopstr. **Nicht** für die Kunden-Clips (die folgen
den Markenprofilen der Kunden).

- `tokens.css`: CSS-Variablen (Single Source of Truth). Wird in `apps/web/app/globals.css` importiert
  und dort über Tailwind v4 `@theme` auf Utility-Klassen gemappt.
- `tokens.json`: dieselben Werte maschinenlesbar (Figma, Blender, Slides).

## Essenz

Schwarz als Raum, Licht als einzige Farbe, Glas und Chrom als Material.

Metaphern: Handschlag Mensch/Maschine (Halbton-Hand + Drahtgitter-Hand: KI schlägt vor, Mensch
entscheidet), Springer halb Objekt/halb Pixel (Verwandlung Long-Form → Clip), „esc.“-Taste (Nutzer
behält die Kontrolle). Das Logo-Element, die Klinge zwischen „chop“ und „str“, ist der Schnittpunkt,
den ein Mensch setzt.

## Prinzipien

1. Echtes Schwarz (`#000` bis `#0A0A13`), großzügiger Leerraum, ein Held pro Fläche.
2. Farbe nur als Licht (Kanten, Glühen, Dispersion), keine flächigen Farbfüllungen.
3. Tiefe durch Schichten: riesiges Hintergrundwort → Lichtkegel mit Körnung → Glas → Inhalt.
4. Mensch und Maschine visuell trennen: Halbton/Foto für Menschen, Drahtgitter/Haarlinien für KI.
5. Zurückhaltung als Premium-Signal: keine Emojis in der UI, kein lila SaaS-Verlauf, kein Hype-Wording.

## Farbsemantik (strikt)

| Farbe | Bedeutung |
|---|---|
| Weiß `--text` | Aktion |
| Brand-Blau `--brand` `#020CF5` | Marke, Klinge, Lichtkanten. Nie als Fließtext. |
| AI-Blau `--ai` `#2F6BFF` | KI arbeitet / KI-Vorschlag ausgewählt |
| Orange `--attention` `#FF7A45` | Mensch muss prüfen. Sonst nie. |
| Spektrum | nur Verwandlungsmomente (Clip entsteht, Render fertig) |

## Komponenten (apps/web/components/ui)

Pill-Navigation (Glas, mittig schwebend), Buttons (weiße Pill / Ghost-Pill), Glas-Karten (Radius 30 px,
1-px-Lichtrand, helle Innenkante oben, Auswahl = `--ai-glow`), Toggle (weiß/schwarz), Status-Check
(helles Icon im `#27272A`-Kreis), Grain-Overlay (SVG-Noise, nie über Text), Lichtkegel, Hintergrundwort.

## Bewegung

400–700 ms, weiche Kurven, nichts springt. Spektral-Glitch nur bei Verwandlung.
`prefers-reduced-motion` → nur Opacity-Übergänge.

## Qualitätsgrenzen

WCAG AA für allen Text. Fallback ohne `backdrop-filter`. Fonts self-hosted (Geist, Geist Mono über
das npm-Paket `geist`, keine Google-Fonts-Einbindung zur Laufzeit). Preise im DACH-Format.
