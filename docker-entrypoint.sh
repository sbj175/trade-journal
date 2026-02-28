#!/bin/bash
set -e

# Run alembic migrations unless SKIP_MIGRATIONS=1 (admin service skips)
if [ "${SKIP_MIGRATIONS}" != "1" ]; then
  echo "Running database migrations..."
  alembic upgrade head
fi

# APP_MODULE defaults to app:app, overridden to admin_app:app for admin service
# APP_PORT defaults to 8000, overridden to 8001 for admin service
exec uvicorn "${APP_MODULE:-app:app}" \
  --host 0.0.0.0 \
  --port "${APP_PORT:-8000}" \
  ${UVICORN_ARGS}
