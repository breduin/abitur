#!/bin/bash
set -e

mkdir -p /app/data

python manage.py migrate --noinput
python manage.py ensure_seed_data
python manage.py collectstatic --noinput

exec "$@"
