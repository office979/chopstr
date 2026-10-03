#!/usr/bin/env bash
# Misst jede Schnittstelle nach: abgeschnittene Wörter, Tonknacksen, Bildsprung.
#
#   ./werkzeuge/04-nahtstellen-pruefen.sh schnitte/tipp1.zeitzuordnung.json
set -euo pipefail
Z="${1:?Zeitzuordnung fehlt}"
[ -f "$Z" ] || { echo "FEHLER: '$Z' gibt es nicht."; exit 1; }

DATEI=$(python3 -c "import json;print(json.load(open('$Z'))['geschnitteneDatei'])")
# macOS bringt bash 3.2 mit — dort gibt es kein mapfile.
NAHT=()
while IFS= read -r zeile; do [ -n "$zeile" ] && NAHT+=("$zeile"); done < <(python3 -c "import json;[print(n) for n in json.load(open('$Z'))['nahtstellen']]")
echo "Datei: $DATEI"
echo "Nahtstellen: ${#NAHT[@]}"; echo

pegel() { ffmpeg -hide_banner -ss "$1" -t "$2" -i "$DATEI" -af volumedetect -f null - 2>&1 \
          | grep -o 'max_volume: [-0-9.]*' | grep -o '[-0-9.]*$' | head -1; }

BEFUNDE=0
for t in "${NAHT[@]}"; do
  VOR=$(python3 -c "print(max(0,$t-0.12))")
  V=$(pegel "$VOR" 0.12); N=$(pegel "$t" 0.12)
  printf "  %6.2fs  davor %7s dB   danach %7s dB   " "$t" "${V:-?}" "${N:-?}"
  SCHNITT_IM_WORT=$(python3 -c "
v=${V:--99}; n=${N:--99}
print('JA' if (v>-45 and n>-45) else 'nein')")
  SPRUNG=$(python3 -c "print('JA' if abs(${V:--99}-${N:--99})>20 else 'nein')")
  if [ "$SCHNITT_IM_WORT" = "JA" ]; then echo "FEHLER: klingt beidseitig — Schnitt liegt im Wort"; BEFUNDE=$((BEFUNDE+1))
  elif [ "$SPRUNG" = "JA" ]; then echo "WARNUNG: Pegelsprung über 20 dB — mögliches Knacksen"; BEFUNDE=$((BEFUNDE+1))
  else echo "ok"; fi

  # Bildsprung: Einzelbilder 80 ms vor und nach der Naht vergleichen
  B=$(python3 -c "print(max(0,$t-0.08))")
  TMP=$(mktemp -d)
  ffmpeg -hide_banner -v error -ss "$B" -i "$DATEI" -frames:v 1 "$TMP/a.png" -y 2>/dev/null
  ffmpeg -hide_banner -v error -ss "$(python3 -c "print($t+0.08)")" -i "$DATEI" -frames:v 1 "$TMP/b.png" -y 2>/dev/null
  if [ -f "$TMP/a.png" ] && [ -f "$TMP/b.png" ]; then
    D=$(ffmpeg -hide_banner -i "$TMP/a.png" -i "$TMP/b.png" -filter_complex "blend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG" -f null - 2>&1 | grep -o 'YAVG=[0-9.]*' | grep -o '[0-9.]*$' | head -1)
    echo "          Bildunterschied über die Naht: ${D:-?}  (über 12 = sichtbarer Sprung, prüfen)"
  fi
  rm -rf "$TMP"
done

echo
echo "=== Gesamte Datei ==="
ffprobe -v error -show_entries format=duration -show_entries stream=codec_type,width,height,r_frame_rate,nb_frames -of default=noprint_wrappers=1 "$DATEI"
TON=$(ffmpeg -hide_banner -i "$DATEI" -af volumedetect -f null - 2>&1 | grep -o 'max_volume: [-0-9.]*' | head -1)
echo "  $TON"
MAXV=$(echo "$TON" | grep -o '[-0-9.]*$')
python3 -c "
m=float('${MAXV:--99}')
print('  FEHLER: Die Datei ist praktisch stumm. Häufigste Ursache: <audio> ohne id.' if m<-60 else '  Ton vorhanden.')"
ANZ=$(ffprobe -v error -select_streams a -show_entries stream=index -of csv=p=0 "$DATEI" | wc -l | tr -d ' ')
[ "$ANZ" -eq 1 ] && echo "  Genau eine Tonspur." || echo "  FEHLER: $ANZ Tonspuren statt einer."

echo
[ "$BEFUNDE" -eq 0 ] && echo "Messbare Nahtstellen-Befunde: keine." || echo "Messbare Nahtstellen-Befunde: $BEFUNDE"
echo "NICHT maschinell geprüft: ob der richtige Take gewählt wurde, ob der Sinn erhalten ist,"
echo "und ob die Untertitel dem hörbaren Text entsprechen. Das braucht Sichtung."
