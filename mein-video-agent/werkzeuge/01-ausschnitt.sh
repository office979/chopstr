#!/usr/bin/env bash
# Schneidet einen Ausschnitt aus einer Aufnahme. Bild und Ton synchron, in eine NEUE Datei.
# Das Original wird nur gelesen. Der Versatz zum Original wird mitgeschrieben.
#
#   ./werkzeuge/01-ausschnitt.sh <aufnahme> <start_s> <dauer_s> [name]
#   ./werkzeuge/01-ausschnitt.sh aufnahmen/roh.mp4 45 60 tipp1
set -euo pipefail

QUELLE="${1:?Aufnahme fehlt}"; START="${2:?Startzeit in Sekunden fehlt}"; DAUER="${3:?Dauer in Sekunden fehlt}"
NAME="${4:-ausschnitt-$(date +%H%M%S)}"
[ -f "$QUELLE" ] || { echo "FEHLER: '$QUELLE' gibt es nicht."; exit 1; }
mkdir -p schnitte

ZIEL="schnitte/${NAME}.mp4"; INFO="schnitte/${NAME}.quelle.json"
[ -e "$ZIEL" ] && { echo "FEHLER: '$ZIEL' existiert schon. Anderen Namen wählen — nichts wird überschrieben."; exit 1; }

echo "Quelle wird gelesen: $QUELLE"
FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of csv=p=0 "$QUELLE")
read -r BREITE HOEHE <<<"$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$QUELLE" | tr ',' ' ')"
GESAMT=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$QUELLE")
TONSPUREN=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$QUELLE" | wc -l | tr -d ' ')
ROTATION=$(ffprobe -v error -select_streams v:0 -show_entries stream_side_data=rotation -of csv=p=0 "$QUELLE" 2>/dev/null | head -1)

echo "  Bildrate: $FPS | Auflösung: ${BREITE}x${HOEHE} | Gesamtdauer: ${GESAMT}s | Tonspuren: $TONSPUREN | Drehung: ${ROTATION:-keine}"
[ "$TONSPUREN" -eq 0 ] && { echo "FEHLER: Die Aufnahme hat keinen Ton. Ohne Ton keine Transkription."; exit 1; }
[ "$TONSPUREN" -gt 1 ] && echo "  ACHTUNG: mehrere Tonspuren — es wird nur die erste verwendet."

# Neu kodieren (nicht -c copy): sonst schneidet der Keyframe-Raster ungenau und Bild/Ton laufen auseinander.
ffmpeg -hide_banner -loglevel error -ss "$START" -i "$QUELLE" -t "$DAUER" \
  -map 0:v:0 -map 0:a:0 \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart -avoid_negative_ts make_zero "$ZIEL"

IST=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$ZIEL")
SUMME=$(shasum -a 256 "$QUELLE" | cut -d' ' -f1)

cat > "$INFO" <<JSON
{
  "ausschnitt": "$ZIEL",
  "originalaufnahme": "$QUELLE",
  "pruefsummeOriginal": "$SUMME",
  "offsetZumOriginal": $START,
  "angeforderteDauer": $DAUER,
  "tatsaechlicheDauer": $IST,
  "bildrate": "$FPS",
  "breite": $BREITE,
  "hoehe": $HOEHE,
  "erstelltAm": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "hinweis": "Zeiten im Transkript dieses Ausschnitts sind AUSSCHNITT-Zeiten. Originalzeit = Ausschnittzeit + offsetZumOriginal."
}
JSON

echo
echo "Fertig: $ZIEL  (${IST}s)"
echo "Herkunft: $INFO"
echo "WICHTIG: Versatz zum Original ist ${START}s. Alle weiteren Zeiten sind Ausschnitt-Zeiten."
