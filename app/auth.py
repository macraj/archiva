import os
import os
import hmac
import hashlib
import base64
from typing import Optional

SECRET = os.environ.get("ARCHIVA_SESSION_SECRET", "dev-change-me")

def sign(data: str) -> str:
    sig = hmac.new(SECRET.encode(), data.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode()

def make_session(user_id: int, is_admin: bool) -> str:
    data = f"{user_id}:{1 if is_admin else 0}"
    return f"{data}.{sign(data)}"

def parse_session(value: str) -> Optional[tuple[int, bool]]:
    try:
        data, sig = value.rsplit(".", 1)
        if not hmac.compare_digest(sign(data), sig):
            return None
        uid_s, admin_s = data.split(":")
        return int(uid_s), (admin_s == "1")
    except Exception:
        return None

