#!/usr/bin/env bash
# Restore a production dump into the staging stack and start it.
#   tools/staging/up.sh ~/targetolog-backup/db-2026-10-29_184438.sql.gz
# Run again with a dump to start over from it; without one it only starts
# what is already restored. Never points at the production server.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
compose=(docker compose -f "$here/compose.yaml")
keyfile="$here/.encryption-key"

if [[ ! -s "$keyfile" ]]; then
  python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())" >"$keyfile"
fi
export STAGING_ENCRYPTION_KEY="$(cat "$keyfile")"

dump="${1:-}"
if [[ -n "$dump" ]]; then
  [[ -f "$dump" ]] || { echo "no such dump: $dump" >&2; exit 1; }
  "${compose[@]}" down --volumes
  "${compose[@]}" up -d --wait db
  echo "restoring $dump ..."
  gzip -dc "$dump" | "${compose[@]}" exec -T db psql -q -U targetolog -d targetolog -v ON_ERROR_STOP=1 >/dev/null
  "${compose[@]}" build api
  # A Django dump has no alembic_version: mark it as the baseline, as production was.
  "${compose[@]}" run --rm --no-deps api alembic stamp 0001
  "${compose[@]}" run --rm --no-deps api alembic upgrade head
fi

"${compose[@]}" up -d --build api worker
echo "staging: http://localhost:8200  (db 127.0.0.1:55433, user targetolog / staging)"
