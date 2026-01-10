from cryptography.fernet import Fernet
from itsdangerous import URLSafeSerializer

from .config import CRED_KEY, SESSION_SECRET

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
fernet = Fernet(CRED_KEY.encode() if isinstance(CRED_KEY, str) else CRED_KEY)
cookie = URLSafeSerializer(SESSION_SECRET)

def hash_password(p: str) -> str:
    return pwd.hash(p)

def verify_password(p: str, hashed: str) -> bool:
    return pwd.verify(p, hashed)

def encrypt_secret(p: str) -> str:
    return fernet.encrypt(p.encode()).decode()

def decrypt_secret(t: str) -> str:
    return fernet.decrypt(t.encode()).decode()

def sign_session(user_id: int) -> str:
    return cookie.dumps({"user_id": user_id})

def unsign_session(value: str) -> int | None:
    try:
        data = cookie.loads(value)
        return int(data["user_id"])
    except Exception:
        return None


