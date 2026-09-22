# chopstr Markenassets

Quelle: Designer-Export aus Adobe Illustrator (21.09.2026). Die Originale liegen hier unverändert:

- `chopstr-logo-original-with-palette.svg`: Logo auf 2160×2160-Fläche in `#0a0a13` mit Farbpalette.
- `chopstr-logo-original-transparent.svg`: Logo ohne Hintergrund.

Beide Originale referenzieren die Schrift **SF Pro Display Bold** als `<text>`. Ohne installierte
Schrift rendern Browser den Schriftzug falsch. Für die App wurden die Buchstaben deshalb mit der
lokal installierten SF Pro Display Bold (Kerning über HarfBuzz) in Pfade umgewandelt. Die
umgerissenen Versionen liegen in `apps/web/public/brand/`:

| Datei | Verwendung |
|---|---|
| `chopstr-wordmark.svg` | Wortmarke, transparent, helle Schrift. Navigation, Dark UI. |
| `chopstr-wordmark-on-dark.svg` | Wortmarke auf `#0a0a13`. Social-Profile, Slides. |
| `chopstr-wordmark-black.svg` | Wortmarke, dunkle Schrift. Helle Dokumente, Rechnungen. |
| `chopstr-mark.svg` | Nur die Klinge (Bildmarke), transparent. Favicon, Ladeanzeige. |
| `chopstr-mark-app.svg` | Klinge auf abgerundeter `#0a0a13`-Kachel. App-Icon, PWA. |

## Farben (aus dem Logo)

| Token | Hex | Rolle |
|---|---|---|
| `--brand` | `#020CF5` | Klinge, Unterstrich links, Lichtkanten |
| `--brand-deep` | `#1B1A62` | Unterstrich rechts, Flächen für KI-Vorschläge |
| `--bg-raised` | `#0A0A13` | Erhobene Flächen, Logo-Hintergrund |
| `--text` | `#F4F5FE` | Schriftzug, Primärtext |

Die Klinge zwischen „chop“ und „str“ ist das Signaturelement: der Schnittpunkt, den der Mensch setzt.
