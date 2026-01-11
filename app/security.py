from passlib.context import CryptContext
from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import URLSafeSerializer
import logging
from typing import Optional

from .config import CRED_KEY, SESSION_SECRET

logger = logging.getLogger(__name__)

# Initialize with error handling
try:
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception as e:
    logger.error(f"Failed to initialize CryptContext: {e}")
    raise

try:
    # Ensure CRED_KEY is proper Fernet key
    if isinstance(CRED_KEY, str):
        key_bytes = CRED_KEY.encode()
    else:
        key_bytes = CRED_KEY
    
    fernet = Fernet(key_bytes)
    logger.info("Fernet initialized successfully")
except ValueError as e:
    logger.error(f"Invalid Fernet key: {e}")
    logger.error(f"Key value (first 20 chars): {CRED_KEY[:20] if CRED_KEY else 'None'}")
    logger.error("Generate a proper key with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'")
    raise
except Exception as e:
    logger.error(f"Failed to initialize Fernet: {e}")
    raise

try:
    cookie = URLSafeSerializer(SESSION_SECRET)
except Exception as e:
    logger.error(f"Failed to initialize URLSafeSerializer: {e}")
    raise

def hash_password(p: str) -> str:
    """Hashowanie hasła"""
    return pwd.hash(p)

def verify_password(p: str, hashed: str) -> bool:
    """Weryfikacja hasła"""
    return pwd.verify(p, hashed)

def encrypt_secret(p: str) -> str:
    """Szyfrowanie sekretu (hasła IMAP)"""
    try:
        return fernet.encrypt(p.encode()).decode()
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        raise ValueError(f"Cannot encrypt secret: {e}")

def decrypt_secret(t: str) -> str:
    """Odszyfrowywanie sekretu"""
    try:
        return fernet.decrypt(t.encode()).decode()
    except InvalidToken:
        logger.error("Decryption failed: Invalid token (wrong key?)")
        raise ValueError("Cannot decrypt secret - invalid token. Possible key mismatch.")
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        raise ValueError(f"Cannot decrypt secret: {e}")

def sign_session(user_id: int) -> str:
    """Podpisywanie sesji"""
    return cookie.dumps({"user_id": user_id})

def unsign_session(value: str) -> Optional[int]:
    """Weryfikacja i odczyt sesji"""
    try:
        data = cookie.loads(value)
        return int(data["user_id"])
    except Exception:
        return None
