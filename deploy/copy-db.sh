#!/usr/bin/env bash
# Copies the database and media of the old Django project into this one's
# own containers. The old project keeps running; it is only read.
#
#   bash deploy/copy-db.sh
#
# Run again to replace the copy with a fresh one.
set -euo pipefail

OLD_DIR=${OLD_DIR:-/opt/targetolog-ai}
# The old project's Postgres container. Found by name when not given:
#   OLD_DB_CONTAINER=targetolog-ai-db-1 bash deploy/copy-db.sh
OLD_DB_CONTAINER=${OLD_DB_CONTAINER:-$(docker ps --format '{{.Names}}' \
    | grep -i 'targetolog' | grep -iE 'db|postgres' | grep -v '^target-' | head -n1)}
[ -n "$OLD_DB_CONTAINER" ] || { echo "Eski baza konteyneri topilmadi: OLD_DB_CONTAINER=... bering"; exit 1; }

cd "$(dirname "$0")/.."
mkdir -p backups media logs
DUMP=backups/django-$(date +%Y%m%d-%H%M%S).dump

echo "1/5 Eski bazadan dump ($OLD_DB_CONTAINER): $DUMP"
docker exec "$OLD_DB_CONTAINER" \
    sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' > "$DUMP"
test -s "$DUMP" || { echo "Dump bo'sh chiqdi"; exit 1; }

echo "2/5 api va worker to'xtatiladi, yangi baza ishga tushadi"
docker compose stop api worker 2>/dev/null || true
docker compose up -d --wait db redis

echo "3/5 Yangi bazaga yuklash"
docker compose exec -T db psql -U targetolog -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS targetolog WITH (FORCE);" \
    -c "CREATE DATABASE targetolog OWNER targetolog;"
docker compose exec -T db pg_restore -U targetolog -d targetolog \
    --no-owner --no-acl --exit-on-error < "$DUMP"

echo "4/5 Media fayllar"
if [ -d "$OLD_DIR/media" ]; then
    cp -a "$OLD_DIR/media/." media/
fi
chown -R 1000:1000 media logs

echo "5/5 Alembic: jadvallar bor, faqat belgilanadi"
docker compose run --rm --no-deps api alembic stamp 0001
docker compose run --rm --no-deps api alembic upgrade head

docker compose up -d --build
echo "Tayyor. Tekshirish: curl -s http://127.0.0.1:8100/health"
