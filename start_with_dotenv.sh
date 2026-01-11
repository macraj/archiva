# Stwórz skrypt startowy który używa python-dotenv
cat > /opt/archiva/start_with_dotenv.sh << 'EOF'
#!/bin/sh
cd /opt/archiva

# Użyj Pythona do załadowania .env przez python-dotenv
.venv/bin/python -c "
import os
from dotenv import load_dotenv

# Załaduj .env
load_dotenv('/opt/archiva/.env')

# Sprawdź
key = os.environ.get('ARCHIVA_CRED_KEY')
print(f'Loaded ARCHIVA_CRED_KEY: {key[:20]}... (length: {len(key)})')

# Test Fernet
from cryptography.fernet import Fernet
try:
    Fernet(key.encode())
    print('✓ Fernet key is valid')
except Exception as e:
    print(f'✗ Fernet error: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "Failed to load .env or invalid key"
    exit 1
fi

# Uruchom aplikację - środowisko jest już załadowane
exec .venv/bin/uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --log-level info
EOF

chmod +x /opt/archiva/start_with_dotenv.sh