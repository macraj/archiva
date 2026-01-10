import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("ARCHIVA_DATA_DIR", "/mnt/data/archiva"))
DB_PATH = Path(os.environ.get("ARCHIVA_DB_PATH", str(DATA_DIR / "db" / "app.db")))

# wymagane do szyfrowania haseł IMAP (Fernet)
CRED_KEY = os.environ["ARCHIVA_CRED_KEY"]

# sekret do podpisywania ciasteczka sesji
SESSION_SECRET = os.environ.get("ARCHIVA_SESSION_SECRET", CRED_KEY)

# self-signup on/off
ALLOW_SIGNUP = os.environ.get("ARCHIVA_ALLOW_SIGNUP", "1") == "1"

