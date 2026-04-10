#!/bin/bash
set -e

# Run alembic migrations unless SKIP_MIGRATIONS=1 (admin service skips)
if [ "${SKIP_MIGRATIONS}" != "1" ]; then
  echo "Running database migrations..."
  # On a fresh database, alembic upgrade fails because old migrations reference
  # tables that don't exist yet. Detect this and use create_all + stamp instead.
  if ! alembic upgrade head 2>/dev/null; then
    echo "Alembic upgrade failed — initializing fresh database with create_all..."
    python -c "
from src.database.engine import init_engine
from src.database.models import Base
import os
engine = init_engine(os.environ['DATABASE_URL'])
Base.metadata.create_all(engine)
print('Tables created successfully')
"
    alembic stamp head
    echo "Database initialized and stamped at head"
  fi
fi

# APP_MODULE defaults to app:app, overridden to admin_app:app for admin service
# APP_PORT defaults to 8000, overridden to 8002 for admin service
exec uvicorn "${APP_MODULE:-app:app}" \
  --host 0.0.0.0 \
  --port "${APP_PORT:-${PORT:-8000}}" \
  ${UVICORN_ARGS}
