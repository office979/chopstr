#!/usr/bin/env bash
# Transkribiert lokal mit whisper.cpp und prüft das Ergebnis wirklich nach.
#
#   ./werkzeuge/02-transkribieren.sh <datei> [sprache] [modell]
#   ./werkzeuge/02-transkribieren.sh schnitte/tipp1.mp4 de small
set -euo pipefail

DATEI="${1:?Datei fehlt}"; SPRACHE="${2:-de}"; MODELL="${3:-small}"
[ -f "$DATEI" ] || { echo "FEHLER: '$DATEI' gibt es nicht."; exit 1; }

# Ein .en-Modell würde deutsches Audio still ins Englische ÜBERSETZEN.
case "$MODELL" in
  *.en) echo "FEHLER: '$MODELL' ist ein reines Englisch-Modell. Es übersetzt Deutsch still ins Englische."
        echo "       Nimm 'small', 'medium' oder 'large-v3' — ohne .en"; exit 1;;
esac
command -v whisper-cli >/dev/null || { echo "FEHLER: whisper-cli fehlt. Installieren: brew install whisper.cpp"; exit 1; }

BASIS="${DATEI##*/}"; BASIS="${BASIS%.*}"
ZIEL="schnitte/${BASIS}.transcript.json"
mkdir -p schnitte

echo "Transkribiere lokal ($MODELL, Sprache $SPRACHE). Nichts wird hochgeladen."
export HYPERFRAMES_SKIP_SKILLS=1
ERG=$(npx --yes hyperframes@0.8.77 transcribe "$DATEI" \
        --engine whisper --model "$MODELL" --language "$SPRACHE" --dir . --json 2>&1 | tail -1)
echo "$ERG"

# Nicht nur der Exit-Code zählt.
echo "$ERG" | grep -q '"ok":true' || { echo "FEHLER: transcribe meldet nicht ok:true. Abbruch."; exit 1; }
[ -f transcript.json ] || { echo "FEHLER: transcript.json wurde nicht erzeugt."; exit 1; }
mv transcript.json "$ZIEL"

python3 - "$ZIEL" "$DATEI" <<'PY'
import json,sys,subprocess
p,media=sys.argv[1],sys.argv[2]
d=json.load(open(p))
if not isinstance(d,list) or not d: print("FEHLER: Transkript ist leer."); sys.exit(1)
dauer=float(subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",media],
                           capture_output=True,text=True).stdout.strip())
fehler=[]; prev=-1.0
for i,w in enumerate(d):
    s,e=w.get("start"),w.get("end")
    if s is None or e is None: fehler.append(f"Wort {i} ohne Zeit"); break
    if e<s: fehler.append(f"Wort {i}: Ende vor Start")
    if s<prev-0.01: fehler.append(f"Wort {i}: Zeit läuft rückwärts")
    if e>dauer+0.5: fehler.append(f"Wort {i}: Zeit {e}s liegt hinter dem Ende ({dauer}s)")
    prev=s
txt=" ".join(str(w.get("text","")).strip() for w in d)
print(f"\n  Wörter: {len(d)}   Mediendauer: {dauer:.2f}s   Letztes Wort endet: {d[-1]['end']}s")
print(f"  Text: {txt[:220]}{'…' if len(txt)>220 else ''}")
if fehler:
    print("\n  UNPLAUSIBEL:"); [print("   -",f) for f in fehler[:8]]; sys.exit(1)
print("\n  Wortzeiten plausibel: monoton, innerhalb der Dauer, Ende nach Start.")
PY

echo "Transkript: $ZIEL"
