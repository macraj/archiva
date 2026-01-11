#!/bin/sh
# Archiva - Production Start Script
# No auto-reload, better for production

cd /opt/archiva

# Log startup
echo "[$(date)] Starting Archiva in production mode" >> /var/log/archiva/start.log

# Set environment from .env file if exists
if [ -f .env ]; then
    echo "[$(date)] Loading .env file" >> /var/log/archiva/start.log
    # Simple .env loading
    while IFS='=' read -r key value; do
        # Remove comments and empty lines
        if [[ ! "$key" =~ ^# ]] && [[ -n "$key" ]]; then
            # Remove quotes
            value="${value%\"}"
            value="${value#\"}"
            value="${value%\'}"
            value="${value#\'}"
            export "$key=$value"
            echo "  Set $key" >> /var/log/archiva/start.log
        fi
    done < .env
fi

# Ensure required environment variables
export ARCHIVA_CRED_KEY="${ARCHIVA_CRED_KEY:-Gd7q3bLkP9sJm5tRv2wXyZ8A1B4C6D0E_F-HiJkLoNpQ}"
export ARCHIVA_DATA_DIR="${ARCHIVA_DATA_DIR:-/mnt/data/archiva}"
export ARCHIVA_DB_PATH="${ARCHIVA_DB_PATH:-/mnt/data/archiva/db/app.db}"
export ARCHIVA_SESSION_SECRET="${ARCHIVA_SESSION_SECRET:-${ARCHIVA_CRED_KEY}}"
export ARCHIVA_ALLOW_SIGNUP="${ARCHIVA_ALLOW_SIGNUP:-1}"
export PYTHONPATH="/opt/archiva"

# Check Fernet key
if [ "$ARCHIVA_CRED_KEY" = "TU_WSTAW_STALY_KLUCZ_FERNET" ]; then
    echo "ERROR: Please set a proper Fernet key in .env file!" >> /var/log/archiva/start.log
    echo "Run: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'" >> /var/log/archiva/start.log
    exit 1
fi

# Create necessary directories
mkdir -p /mnt/data/archiva/db
mkdir -p /var/log/archiva

echo "[$(date)] Starting uvicorn with 2 workers" >> /var/log/archiva/start.log

# Start uvicorn in production mode
exec .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 2 \
    --log-level info \
    --no-access-log \
    --proxy-headers \
    --limit-concurrency 100 \
    --timeout-keep-alive 30
