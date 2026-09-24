# Fonts für den Render

`Inter-Bold.otf` wird von `pipeline/render.py` für Titelkarte und Hook-Overlay (`drawtext`) und als
Font-Verzeichnis für libass (`subtitles=...:fontsdir=`) verwendet. Der Renderer sucht in dieser
Reihenfolge: `Inter-Bold.ttf`, `Inter-Bold.otf`. Fehlt beides, werden Titelkarte und Hook-Overlay
übersprungen und der Render meldet das als Hinweis.

Lizenz: Inter von Rasmus Andersson, SIL Open Font License 1.1 (https://github.com/rsms/inter).
Die OFL erlaubt Einbetten, Bündeln und kommerzielle Nutzung; die Schrift darf nicht unter ihrem
Namen verändert weiterverbreitet werden.

Im Docker-Image kommt Inter über das Paket `fonts-inter`; der Pfad lässt sich per
`RENDER_FONTS_DIR` überschreiben.

## Untertitel-Schriften zur Auswahl

`packages/design/caption_fonts.json` listet die Schriften, die im Clip-Editor wählbar sind. Der
Renderer sucht die dort genannte Datei in diesem Ordner. Fehlt sie, bleibt es bei der Vorgabe und
der Render schreibt einen Hinweis in den Plan; im Editor sagt es die Vorschau.

Alle gelisteten Schriften stehen unter der SIL Open Font License 1.1 oder Apache 2.0, dürfen also
gebündelt und gewerblich genutzt werden. Sie liegen bewusst nicht im Repository: Schriftdateien
sind Binärdateien, und wer sie nicht braucht, soll sie nicht mitladen.

Nach dem Ablegen einer Datei:

    node scripts/sync-fonts.mjs

Das spiegelt sie nach `apps/web/public/fonts`, damit die Vorschau im Editor dieselbe Schrift zeigt,
die der Renderer einbrennt. Das Skript nennt auch, welche Dateien noch fehlen.
