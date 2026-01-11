#!/bin/sh
set -eu

APP_DIR="/opt/archiva"
DATA_DIR="/mnt/data/archiva"
VENV_DIR="$APP_DIR/.venv"

SECRET_DIR="/etc/archiva"
SECRET_ENV="$SECRET_DIR/archiva.env"

DB_FILE="$DATA_DIR/db/app.db"

# mniej gadania
apk update >/dev/null
apk add --no-cache \
  python3 py3-pip \
  python3-dev build-base musl-dev \
  libffi-dev openssl-dev \
  sqlite sqlite-libs \
  git curl >/dev/null

mkdir -p "$APP_DIR" "$DATA_DIR/db" "$DATA_DIR/storage" "$DATA_DIR/logs"
chmod 700 "$DATA_DIR" 2>/dev/null || true

python3 -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"

pip install -U pip >/dev/null
pip install \
  fastapi uvicorn[standard] \
  jinja2 python-multipart \
  sqlalchemy aiosqlite \
  passlib argon2-cffi \
  cryptography \
  itsdangerous \
  email-validator >/dev/null

# --- secrets: generate once, root-only ---
mkdir -p "$SECRET_DIR"
chmod 700 "$SECRET_DIR"

NEW_SECRETS=0
ADMIN_PASSWORD=""

if [ ! -f "$SECRET_ENV" ]; then
  umask 077
  CRED_KEY="$("$VENV_DIR/bin/python" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")"
  ADMIN_PASSWORD="$("$VENV_DIR/bin/python" -c "import secrets; print(secrets.token_urlsafe(9))")"

  {
    echo "ARCHIVA_CRED_KEY=$CRED_KEY"
    echo "ARCHIVA_ADMIN_EMAIL=admin@archivaexample.com"
    echo "ARCHIVA_ADMIN_PASSWORD=$ADMIN_PASSWORD"
  } > "$SECRET_ENV"

  chmod 600 "$SECRET_ENV"
  NEW_SECRETS=1
fi

# --- sanitize existing DB (if any): remove IMAP passwords + disable accounts ---
# --- sanitize DB only when NEW_SECRETS=1 (new CRED key) ---
if [ -f "$DB_FILE" ]; then
  if [ "$NEW_SECRETS" -eq 1 ]; then
    TOTAL_ACCOUNTS="$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM mail_accounts;")"
    ENABLED_BEFORE="$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM mail_accounts WHERE enabled = 1;")"

    sqlite3 "$DB_FILE" <<'SQL'
UPDATE mail_accounts SET enabled = 0 WHERE enabled = 1;
UPDATE mail_accounts SET imap_password_enc = '';
SQL

    echo "DB found: $DB_FILE"
    echo "Mail accounts found: $TOTAL_ACCOUNTS"
    echo "Mail accounts disabled (new CRED key): $ENABLED_BEFORE"
  else
    echo "DB found: $DB_FILE"
    echo "Secrets unchanged -> DB left intact"
  fi
else
  echo "DB not found: $DB_FILE (skip mail account reset)"
fi
# --- end sanitize existing DB ---

echo "Install OK"
echo "Secrets: $SECRET_ENV (chmod 600)"

if [ "$NEW_SECRETS" -eq 1 ]; then
  echo ""
  echo "=== ARCHIVA ADMIN CREDENTIALS (pokazane tylko teraz) ==="
  echo "login: admin@example.coml"
  echo "password: $ADMIN_PASSWORD"
  echo "======================================================="
  echo ""
else
  echo "Admin credentials not displayed (secrets file already existed)."
fi
echo "Please restart the Archiva service."