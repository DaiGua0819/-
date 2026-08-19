#!/usr/bin/env bash
set -Eeuo pipefail

POSTGRES_BIN="/usr/lib/postgresql/16/bin"
POSTGRES_DATA_DIR="/data/postgres"
REDIS_DATA_DIR="/data/redis"

mkdir -p "${POSTGRES_DATA_DIR}" "${REDIS_DATA_DIR}"

if [[ ! -s "${POSTGRES_DATA_DIR}/PG_VERSION" ]]; then
  "${POSTGRES_BIN}/initdb" \
    --pgdata="${POSTGRES_DATA_DIR}" \
    --username=xvi \
    --auth-local=trust \
    --auth-host=trust
fi

if [[ ! -f "${POSTGRES_DATA_DIR}/.xvi_database_initialized" ]]; then
  "${POSTGRES_BIN}/pg_ctl" \
    --pgdata="${POSTGRES_DATA_DIR}" \
    --options="-c config_file=/app/docker/single-container/postgresql.conf" \
    --log="/tmp/xvi-postgres-init.log" \
    --wait start
  "${POSTGRES_BIN}/createdb" --host=127.0.0.1 --port=5432 --username=xvi xvi
  "${POSTGRES_BIN}/pg_ctl" --pgdata="${POSTGRES_DATA_DIR}" --mode=fast stop
  touch "${POSTGRES_DATA_DIR}/.xvi_database_initialized"
fi

exec supervisord --nodaemon --configuration /app/docker/single-container/supervisord.conf
