# Schriften für den Render

Hier liegen alle Schriften, die chopstr in Untertitel einbrennt. **Sie sind Teil des Repositories.**
Wer chopstr auscheckt, kann jede Schrift aus der Auswahl sofort benutzen; niemand muss vorher etwas
herunterladen oder installieren.

`Inter-Bold.otf` ist die Vorgabe. `pipeline/render.py` benutzt sie für Titelkarte und Hook-Overlay
(`drawtext`) und den ganzen Ordner als Font-Verzeichnis für libass
(`subtitles=...:fontsdir=`). Der Pfad lässt sich per `RENDER_FONTS_DIR` überschreiben; im
Docker-Image liegt der Ordner unter `/app/workers/fonts` (beide Dockerfiles kopieren ihn).

## Die Auswahl

`packages/design/caption_fonts.json` ist die eine Liste: der Worker prüft damit die Wahl und findet
die Datei, die Oberfläche baut daraus die Auswahl im Editor. Was dort steht, muss hier liegen -
`workers/tests/test_schriften.py` besteht darauf.

| Schrift | Datei | Herkunft |
|---|---|---|
| Inter | `Inter-Bold.otf` | github.com/rsms/inter |
| Anton | `Anton-Regular.ttf` | google/fonts, `ofl/anton` |
| Bebas Neue | `BebasNeue-Regular.ttf` | google/fonts, `ofl/bebasneue` |
| Archivo Black | `ArchivoBlack-Regular.ttf` | google/fonts, `ofl/archivoblack` |
| Poppins | `Poppins-Bold.ttf` | google/fonts, `ofl/poppins` |
| Montserrat | `Montserrat-Bold.ttf` | aus `Montserrat[wght].ttf` geschnitten |
| Oswald | `Oswald-Bold.ttf` | aus `Oswald[wght].ttf` geschnitten |
| Playfair Display | `PlayfairDisplay-Bold.ttf` | aus `PlayfairDisplay[wght].ttf` geschnitten |
| Space Grotesk | `SpaceGrotesk-Bold.ttf` | aus `SpaceGrotesk[wght].ttf` geschnitten |

„Geschnitten" heisst: Google liefert diese vier nur noch als variable Schrift, also als eine Datei
mit stufenloser Strichstärke. libass und ffmpeg nehmen daraus die Voreinstellung, und die ist
Normalstärke - wer „Montserrat" wählt, bekäme dünne Untertitel, ohne dass es jemand merkt. Deshalb
wird daraus eine feste Fassung bei Strichstärke 700 erzeugt.

Erneut beschaffen oder eine weitere Schrift aufnehmen:

    cd workers && .venv/bin/python -m scripts.schriften_holen        # fehlende holen
    cd workers && .venv/bin/python -m scripts.schriften_holen --alle # alle neu holen

## Lizenzen

Alle Schriften stehen unter der **SIL Open Font License 1.1**. Sie erlaubt Bündeln, Einbetten und
gewerbliche Nutzung und verlangt dafür zwei Dinge: der Lizenztext samt Urhebervermerk muss
mitgeliefert werden, und eine veränderte Fassung darf nicht unter dem Namen der Originalschrift
weitergegeben werden.

Die Lizenztexte liegen in `lizenzen/`, einer je Familie, im Wortlaut der Herkunft. `schriften_holen`
holt sie zusammen mit der Schriftdatei; eine Datei ohne ihren Lizenztext kommt hier nicht hinein.

Zur zweiten Pflicht: die vier geschnittenen Fassungen sind veränderte Fassungen im Sinne der
Lizenz - sie bleiben deshalb **im Repository und im Produkt**, wo sie als Teil von chopstr
ausgeliefert werden, und werden nicht als „Montserrat" zum Herunterladen angeboten.

## Die Vorschau im Editor

Next kann nur aus `public/` ausliefern. `scripts/sync-fonts.mjs` spiegelt die Dateien deshalb nach
`apps/web/public/fonts` (dort in `.gitignore`, damit sie nicht zweimal im Repo liegen). Das läuft
automatisch vor `npm run dev` und `npm run build` in `apps/web`; von Hand geht es so:

    node scripts/sync-fonts.mjs
