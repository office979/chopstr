#!/usr/bin/env bash
# chopstr · Lokaler Testmodus ohne Docker (macOS mit Homebrew-Postgres)
#   scripts/local-stack.sh start    Postgres starten (Daten unter .local/pgdata), Datenbank anlegen, Migrationen, Seed
#   scripts/local-stack.sh stop     Postgres stoppen
#   scripts/local-stack.sh status
# Danach: Web mit apps/web/.env.local (siehe scripts/local-env.example) und Worker mit
#   cd workers && source scripts/local_env.sh && python -m chopstr_worker.local_worker
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="${PGBIN:-/opt/homebrew/opt/postgresql@15/bin}"
PGDATA="${PGDATA:-$ROOT/.local/pgdata}"
PGPORT="${PGPORT:-5499}"
DBNAME="${DBNAME:-chopstr}"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export DATABASE_URL="postgres://chopstr@127.0.0.1:${PGPORT}/${DBNAME}"

if [ ! -x "$PGBIN/pg_ctl" ]; then
  echo "Postgres nicht gefunden unter $PGBIN. Installieren: brew install postgresql@15" >&2
  exit 1
fi

case "${1:-}" in
  start)
    mkdir -p "$ROOT/.local"
    if [ ! -d "$PGDATA" ]; then
      "$PGBIN/initdb" -D "$PGDATA" -U chopstr --auth=trust -E UTF8 >/dev/null
      echo "Postgres-Datenverzeichnis angelegt: $PGDATA"
    fi
    if ! "$PGBIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
      "$PGBIN/pg_ctl" -D "$PGDATA" -o "-p $PGPORT -c unix_socket_directories=''" -l "$ROOT/.local/pg.log" start >/dev/null
      sleep 2
    fi
    "$PGBIN/psql" -h 127.0.0.1 -p "$PGPORT" -U chopstr -d postgres -tAc "select 1 from pg_database where datname='$DBNAME'" | grep -q 1 \
      || "$PGBIN/createdb" -h 127.0.0.1 -p "$PGPORT" -U chopstr "$DBNAME"
    (cd "$ROOT" && node scripts/migrate.mjs)
    if [ -x "$ROOT/workers/.venv/bin/python" ]; then
      (cd "$ROOT/workers" && DATABASE_URL="$DATABASE_URL" .venv/bin/python -m scripts.seed_dev) || echo "Seed übersprungen (siehe Meldung oben)"
    else
      echo "Worker-venv fehlt (workers/.venv). Seed übersprungen. Anlegen: cd workers && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'"
    fi
    mkdir -p "$ROOT/.local/storage/chopstr-sources" "$ROOT/.local/storage/chopstr-derived" "$ROOT/.local/work"
    echo
    echo "Bereit. DATABASE_URL=$DATABASE_URL"
    echo "Speicher: $ROOT/.local/storage   Arbeitsordner: $ROOT/.local/work"
    echo "Web:    cp scripts/local-env.example apps/web/.env.local  &&  npm run dev"
    echo "Worker: cd workers && source scripts/local_env.sh && python -m chopstr_worker.local_worker"
    ;;
  stop)
    "$PGBIN/pg_ctl" -D "$PGDATA" stop -m fast
    ;;
  status)
    "$PGBIN/pg_ctl" -D "$PGDATA" status || true
    ;;
  *)
    echo "Aufruf: $0 start|stop|status" >&2
    exit 1
    ;;
esac
