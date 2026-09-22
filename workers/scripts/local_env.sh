#!/usr/bin/env bash
# Umgebung für den lokalen Testmodus des Workers (ohne Docker, Temporal, MinIO, GPU).
#
#   cd workers
#   . .venv/bin/activate
#   source scripts/local_env.sh            # bash oder zsh
#   python -m chopstr_worker.local_worker --once
#
# Bereits gesetzte Variablen bleiben erhalten (DATABASE_URL, LOCAL_STORAGE_DIR, ASR_MODEL_DE, ...).
# Das Skript legt workers/.local/bin an und verlinkt dort das libass-fähige ffmpeg aus imageio-ffmpeg
# (Extra dev) sowie ffprobe aus Homebrew oder dem PATH; .local/bin steht danach vorn im PATH.

if [ -n "${ZSH_VERSION:-}" ]; then
  _chopstr_env_src="${(%):-%x}"
else
  _chopstr_env_src="${BASH_SOURCE[0]:-$0}"
fi
CHOPSTR_WORKERS_DIR="$(cd "$(dirname "$_chopstr_env_src")/.." && pwd)"
export CHOPSTR_WORKERS_DIR
unset _chopstr_env_src

# -- Datenbank und Speicher ------------------------------------------------------------------
export APP_ENV="${APP_ENV:-development}"
export DATABASE_URL="${DATABASE_URL:-postgres://chopstr@127.0.0.1:5499/chopstr}"
export S3_ENDPOINT=""                                        # leer = lokaler Ordner statt S3/MinIO
export LOCAL_STORAGE_DIR="${LOCAL_STORAGE_DIR:-$CHOPSTR_WORKERS_DIR/../.local/storage}"  # gleicher Ordner wie die Web-App (Repo/.local/storage)
export WORKER_WORK_DIR="${WORKER_WORK_DIR:-$CHOPSTR_WORKERS_DIR/../.local/work}"
mkdir -p "$LOCAL_STORAGE_DIR" "$WORKER_WORK_DIR"

# -- Modelle: Heuristik statt LLM, Whisper auf der CPU, keine Diarisierung ohne HF_TOKEN ------
export LLM_PROVIDER="${LLM_PROVIDER:-local-heuristic}"
export ASR_DEVICE="${ASR_DEVICE:-cpu}"
export ASR_COMPUTE="${ASR_COMPUTE:-int8}"
# Auf Hugging Face verifiziert: int8-CTranslate2-Konvertierung von primeline/whisper-large-v3-turbo-german
# (Dateien model.bin, config.json, tokenizer.json, vocabulary.json; Apache-2.0). Mehrsprachige Alternative
# ohne deutschen Fine-Tune: deepdml/faster-whisper-large-v3-turbo-ct2 (MIT). Siehe README, Lokaler Testmodus.
export ASR_MODEL_DE="${ASR_MODEL_DE:-cstr/whisper-large-v3-turbo-german-int8_float32}"
export HF_TOKEN="${HF_TOKEN:-}"                              # leer: Sprechertrennung wird übersprungen

# -- Web-App (Publishing über /api/internal/*) --------------------------------------------------
export APP_INTERNAL_URL="${APP_INTERNAL_URL:-http://localhost:3000}"
export INTERNAL_API_SECRET="${INTERNAL_API_SECRET:-}"

# -- Render: schnelles Preset, ffmpeg mit libass und drawtext -----------------------------------
export RENDER_X264_PRESET="${RENDER_X264_PRESET:-veryfast}"

_chopstr_bin="$CHOPSTR_WORKERS_DIR/.local/bin"
mkdir -p "$_chopstr_bin"
_chopstr_ffmpeg="$(python -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())' 2>/dev/null)"
if [ -n "$_chopstr_ffmpeg" ] && [ -x "$_chopstr_ffmpeg" ]; then
  ln -sfn "$_chopstr_ffmpeg" "$_chopstr_bin/ffmpeg"
else
  echo "local_env: imageio-ffmpeg fehlt (pip install -e '.[dev]'), ffmpeg aus dem PATH wird verwendet" >&2
fi
_chopstr_ffprobe=""
for _p in /opt/homebrew/bin/ffprobe /usr/local/bin/ffprobe "$(command -v ffprobe 2>/dev/null)"; do
  if [ -n "$_p" ] && [ -x "$_p" ] && [ "$_p" != "$_chopstr_bin/ffprobe" ]; then
    _chopstr_ffprobe="$_p"
    break
  fi
done
if [ -n "$_chopstr_ffprobe" ]; then
  ln -sfn "$_chopstr_ffprobe" "$_chopstr_bin/ffprobe"
else
  echo "local_env: ffprobe nicht gefunden (brew install ffmpeg)" >&2
fi
case ":$PATH:" in
  *":$_chopstr_bin:"*) ;;
  *) export PATH="$_chopstr_bin:$PATH" ;;
esac
unset _chopstr_bin _chopstr_ffmpeg _chopstr_ffprobe _p

echo "local_env: DATABASE_URL=$DATABASE_URL"
echo "local_env: LOCAL_STORAGE_DIR=$LOCAL_STORAGE_DIR"
echo "local_env: ASR_MODEL_DE=$ASR_MODEL_DE (ASR_DEVICE=$ASR_DEVICE, ASR_COMPUTE=$ASR_COMPUTE), LLM_PROVIDER=$LLM_PROVIDER"
echo "local_env: ffmpeg=$(command -v ffmpeg) ffprobe=$(command -v ffprobe)"
