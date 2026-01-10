#!/bin/sh
set -eu

APP_DIR="/opt/archiva"
DATA_DIR="/mnt/data/archiva"
VENV_DIR="$APP_DIR/.venv"

. "$VENV_DIR/bin/activate"

# export all variables loaded from env file
set -a
. /etc/archiva/archiva.env
set +a

export ARCHIVA_DATA_DIR="$DATA_DIR"
export ARCHIVA_DB_PATH="$DATA_DIR/db/app.db"

cd "$APP_DIR"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

