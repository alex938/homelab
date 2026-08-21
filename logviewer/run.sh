#!/usr/bin/env bash
# Start the log viewer.
#
#   ./run.sh                 serve on 0.0.0.0:8000 (every interface, incl. the public IP)
#   ./run.sh 0.0.0.0:9000    serve somewhere else
#   DEV=1 ./run.sh           Django's auto-reloading dev server instead of gunicorn
#
# First run creates the virtualenv and installs requirements.
set -euo pipefail
cd "$(dirname "$0")"

BIND="${1:-0.0.0.0:8000}"

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet -q -r requirements.txt

.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py collectstatic --noinput --clear >/dev/null

if [[ "${DEV:-0}" == "1" ]]; then
  export DJANGO_DEBUG=1
  exec .venv/bin/python manage.py runserver "$BIND"
fi

# ONE worker, several threads. The refresh runs in a background thread and is
# guarded by a process-local lock, so a second worker process could start a
# second concurrent refresh. Threads give all the concurrency this needs.
exec .venv/bin/gunicorn config.wsgi:application \
  --bind "$BIND" \
  --workers 1 \
  --threads 8 \
  --timeout 600 \
  --access-logfile - \
  --error-logfile -
