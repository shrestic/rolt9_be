#!/bin/sh
set -e

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  echo "[entrypoint] running alembic migrations..."
  alembic upgrade head
else
  echo "[entrypoint] skipping migrations (RUN_MIGRATIONS!=1)"
fi

echo "[entrypoint] starting: $*"
exec "$@"
