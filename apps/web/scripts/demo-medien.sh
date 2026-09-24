#!/usr/bin/env bash
# Die Medien fuer den Testmodus erzeugen: Video, Filmstreifen und Wellenform.
#
# Im Testmodus gibt es keinen Speicher und keinen Worker. Ohne Medien stuende im Clip-Editor
# ueberall "noch nicht gebaut": kein Bild, keine Einzelbilder, keine Tonspur. Die Dateien hier
# sind synthetisch (ffmpeg testsrc2 und ein Sinuston) und zeigen KEIN echtes Material.
#
# Die Laenge richtet sich nach den Stellen in lib/repo/seed.ts: die frueheste geht bis 63,5 s,
# dazu zehn Sekunden Luft fuer die Timeline. Achtzig Sekunden decken das ab.
#
# Aufruf aus apps/web: bash scripts/demo-medien.sh
set -euo pipefail

hier="$(cd "$(dirname "$0")/.." && pwd)"
wurzel="$(cd "$hier/../.." && pwd)"
ziel="$hier/public/demo"
ff="$wurzel/workers/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
[ -x "$ff" ] || ff="$(command -v ffmpeg)"

dauer=80
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

# Bild: testsrc2 hochkant. Alle acht Sekunden ein harter Wechsel der Farbgebung, damit die
# Einzelbilder in der Timeline unterscheidbar sind und Schnitte sichtbar werden.
# Ton: ein Sinus in Stoessen von 2,6 s mit 1,4 s Pause dazwischen. Die Pausen sind der Grund fuer
# die Tonspur: an ihnen schneidet man.
"$ff" -hide_banner -loglevel error -y \
  -f lavfi -t "$dauer" -i "testsrc2=s=360x640:r=25" \
  -f lavfi -t "$dauer" -i "sine=frequency=210:sample_rate=48000" \
  -filter_complex "[0:v]hue='h=mod(floor(t/8)*67,360)':s=1.1[v];[1:a]volume='(0.55+0.4*sin(2*PI*t*2.7))*if(lt(mod(t,4.0),2.6),1.0,0.03)':eval=frame[a]" \
  -map "[v]" -map "[a]" -c:v libx264 -preset veryslow -crf 36 -g 50 -pix_fmt yuv420p -c:a aac -b:a 48k \
  "$ziel/video.mp4"

# Der Filmstreifen, wie ihn der Renderer baut: zwanzig Bilder nebeneinander, 108 Bildpunkte hoch.
"$ff" -hide_banner -loglevel error -y -i "$ziel/video.mp4" \
  -vf "select='not(mod(n,$(( dauer * 25 / 20 ))))',scale=-1:108,tile=20x1" -frames:v 1 -q:v 4 \
  "$ziel/streifen.jpg"

# Die Wellenform mit derselben Funktion wie im Worker. Eine ausgedachte Kurve wuerde Pausen
# zeigen, die es im Ton nicht gibt.
"$ff" -hide_banner -loglevel error -y -i "$ziel/video.mp4" -ac 1 -ar 16000 -c:a pcm_s16le "$tmp/ton.wav"
(cd "$wurzel/workers" && .venv/bin/python -c "
import json, sys
sys.path.insert(0, '.')
from chopstr_worker.pipeline.signals import wellenform
json.dump(wellenform('$tmp/ton.wav'), open('$ziel/wellenform.json', 'w'), separators=(',', ':'))
")

ls -la "$ziel"
