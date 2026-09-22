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
