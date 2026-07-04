#!/bin/bash
set -e

mkdir -p /app/data

echo "Waiting for database migrations..."
for _ in $(seq 1 60); do
  if python manage.py migrate --check >/dev/null 2>&1; then
    echo "Migrations ready."
    exec "$@"
  fi
  sleep 2
done

echo "Timed out waiting for migrations."
exit 1
