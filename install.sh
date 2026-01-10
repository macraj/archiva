#!/bin/sh
set -eu

APP_DIR="/opt/archiva"
DATA_DIR="/mnt/data/archiva"
VENV_DIR="$APP_DIR/.venv"

SECRET_DIR="/etc/archiva"
SECRET_ENV="$SECRET_DIR/archiva.env"

apk update
apk add --no-cache \
  python3 py3-pip \
  python3-dev build-base musl-dev \
  libffi-dev openssl-dev \
  sqlite sqlite-libs \
  git curl

mkdir -p "$APP_DIR" "$DATA_DIR/db" "$DATA_DIR/storage" "$DATA_DIR/logs"

python3 -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"
pip install -U pip

pip install \
  fastapi uvicorn[standard] \
  jinja2 python-multipart \
  sqlalchemy aiosqlite \
  passlib argon2-cffi \
  cryptography \
  itsdangerous \
  email-validator

# --- secrets: generate once, root-only ---
mkdir -p "$SECRET_DIR"
chmod 700 "$SECRET_DIR"

if [ ! -f "$SECRET_ENV" ]; then
  umask 077
  KEY="$("$VENV_DIR/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
  {
    echo "ARCHIVA_CRED_KEY=$KEY"
    echo "ARCHIVA_ADMIN_EMAIL=admin@archiva.local"
  } > "$SECRET_ENV"
  chmod 600 "$SECRET_ENV"
fi

echo "Install OK"
echo "Secrets: $SECRET_ENV (chmod 600)"
echo "Next: /opt/archiva/run-dev.sh"

