from __future__ import annotations

import imaplib
import socket
import threading
from typing import Optional

from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from pydantic import BaseModel, EmailStr

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func  # Dodaj ten import

from .db import get_db, engine
from .models import Base, User, MailAccount, ArchivedEmail  # Dodaj ArchivedEmail
from .security import (
    hash_password,
    verify_password,
    encrypt_secret,
    decrypt_secret,
    sign_session,
    unsign_session,
)
from .config import ALLOW_SIGNUP
from .archive import sync_account, sync_all_enabled_accounts  # Dodaj te importy

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Archiva")
SESSION_COOKIE = "archiva_session"


def template_globals(request: Request):
    return {"ALLOW_SIGNUP": ALLOW_SIGNUP}


templates = Jinja2Templates(
    directory="app/templates",
    context_processors=[template_globals],
)


# --------- helpers ---------
def normalize_email(email: str) -> str:
    return email.strip().lower()


def imap_smoke_test(host: str, port: int, user: str, password: str, timeout: float = 8.0) -> tuple[bool, str | None]:
    host = host.strip()
    user = user.strip()

    try:
        sock = socket.create_connection((host, int(port)), timeout=timeout)
        sock.close()
    except OSError as exc:
        return False, f"connect: {exc}"

    try:
        mail = imaplib.IMAP4_SSL(host, int(port))
        try:
            typ, _ = mail.login(user, password)
        finally:
            try:
                mail.logout()
            except Exception:
                pass
        if typ != "OK":
            return False, "login failed"
    except imaplib.IMAP4.error as exc:
        return False, f"imap: {exc}"
    except OSError as exc:
        return False, f"net: {exc}"

    return True, None


def has_admin(db: Session) -> bool:
    return db.query(User).filter(User.role == "admin").first() is not None


def get_current_user(request: Request, db: Session):
    """Pobierz aktualnego użytkownika (bez Depends)"""
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    uid = unsign_session(raw)
    if not uid:
        return None
    return db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()

def redirect_login():
    return RedirectResponse("/login", status_code=303)


# --------- form models ---------
class EmailPasswordForm(BaseModel):
    email: EmailStr
    password: str

    @classmethod
    def as_form(
        cls,
        email: EmailStr = Form(...),
        password: str = Form(...),
    ) -> "EmailPasswordForm":
        return cls(email=email, password=password)


class ChangePasswordForm(BaseModel):
    current_password: str
    new_password: str
    new_password2: str

    @classmethod
    def as_form(
        cls,
        current_password: str = Form(...),
        new_password: str = Form(...),
        new_password2: str = Form(...),
    ) -> "ChangePasswordForm":
        return cls(
            current_password=current_password,
            new_password=new_password,
            new_password2=new_password2,
        )


# --------- routes ---------
@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()

    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)

    return RedirectResponse("/accounts", status_code=303)


# --- First-time setup ---
@app.get("/setup", response_class=HTMLResponse)
def setup_get(request: Request, db: Session = Depends(get_db)):
    if has_admin(db):
        return redirect_login()
    return templates.TemplateResponse("setup.html", {"request": request})


@app.post("/setup")
def setup_post(
    request: Request,
    form: EmailPasswordForm = Depends(EmailPasswordForm.as_form),
    db: Session = Depends(get_db),
):
    if has_admin(db):
        return redirect_login()

    email = normalize_email(str(form.email))
    password = form.password

    admin = User(
        email=email,
        password_hash=hash_password(password),
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "setup.html",
            {"request": request, "error": "Email already exists."},
            status_code=400,
        )

    return redirect_login()


# --- Auth ---
@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/login")
def login_post(
    request: Request,
    form: EmailPasswordForm = Depends(EmailPasswordForm.as_form),
    db: Session = Depends(get_db),
):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    email = normalize_email(str(form.email))
    password = form.password

    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid credentials"},
            status_code=400,
        )

        # next_url = "/account/change-password" if user.must_change_password else "/accounts"
    next_url = (
        "/account/change-password"
        if user.must_change_password
        else ("/admin/users" if user.role == "admin" else "/accounts")
    )

    resp = RedirectResponse(next_url, status_code=303)
    resp.set_cookie(
        SESSION_COOKIE,
        sign_session(user.id),
        httponly=True,
        samesite="lax",
    )
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


# --- Signup ---
@app.get("/signup", response_class=HTMLResponse)
def signup_get(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    if not ALLOW_SIGNUP:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Signup disabled"},
            status_code=403,
        )
    return templates.TemplateResponse("signup.html", {"request": request})


@app.post("/signup")
def signup_post(
    request: Request,
    form: EmailPasswordForm = Depends(EmailPasswordForm.as_form),
    db: Session = Depends(get_db),
):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    if not ALLOW_SIGNUP:
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "Signup disabled"},
            status_code=403,
        )

    email = normalize_email(str(form.email))
    password = form.password

    user = User(
        email=email,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        must_change_password=False,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            "signup.html",
            {"request": request, "error": "User already exists"},
            status_code=400,
        )

    return RedirectResponse("/login", status_code=303)


# --- Account: change password ---
@app.get("/account/change-password", response_class=HTMLResponse)
def change_password_get(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()

    return templates.TemplateResponse(
        "change_password.html",
        {"request": request, "user": u},
    )


@app.post("/account/change-password")
def change_password_post(
    request: Request,
    form: ChangePasswordForm = Depends(ChangePasswordForm.as_form),
    db: Session = Depends(get_db),
):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()

    if form.new_password != form.new_password2:
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "user": u, "error": "Passwords do not match"},
            status_code=400,
        )

    if not verify_password(form.current_password, u.password_hash):
        return templates.TemplateResponse(
            "change_password.html",
            {"request": request, "user": u, "error": "Invalid current password"},
            status_code=400,
        )

    u.password_hash = hash_password(form.new_password)
    u.must_change_password = False
    db.add(u)
    db.commit()

    return RedirectResponse("/accounts", status_code=303)


# --- Admin users ---
@app.get("/admin/users", response_class=HTMLResponse)
def admin_users_get(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()
    if u.role != "admin":
        return RedirectResponse("/accounts", status_code=303)

    users = db.query(User).order_by(User.id.asc()).all()
    return templates.TemplateResponse(
        "admin_users.html",
        {"request": request, "user": u, "users": users},
    )


@app.post("/admin/users/{user_id}/delete")
def admin_users_delete(request: Request, user_id: int, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    admin = get_current_user(request, db)
    if not admin:
        return redirect_login()
    if admin.role != "admin":
        return RedirectResponse("/accounts", status_code=303)

    if admin.id == user_id:
        return RedirectResponse("/admin/users", status_code=303)

    victim = db.query(User).filter(User.id == user_id).first()
    if victim:
        db.delete(victim)
        db.commit()

    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/force-password-change")
def admin_users_force_pw(request: Request, user_id: int, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    admin = get_current_user(request, db)
    if not admin:
        return redirect_login()
    if admin.role != "admin":
        return RedirectResponse("/accounts", status_code=303)

    victim = db.query(User).filter(User.id == user_id).first()
    if victim:
        victim.must_change_password = True
        db.add(victim)
        db.commit()

    return RedirectResponse("/admin/users", status_code=303)


# --- Mail accounts ---
@app.get("/accounts", response_class=HTMLResponse)
def accounts_get(request: Request, db: Session = Depends(get_db)):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()

    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)

    accounts = (
        db.query(MailAccount)
        .filter(MailAccount.user_id == u.id)
        .order_by(MailAccount.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        "accounts.html",
        {"request": request, "user": u, "accounts": accounts},
    )


@app.post("/accounts/add")
def accounts_add(
    request: Request,
    name: str = Form(...),
    imap_host: str = Form(...),
    imap_port: int = Form(993),
    imap_user: str = Form(...),
    imap_password: str = Form(...),
    db: Session = Depends(get_db),
):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=303)

    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)

    acc = MailAccount(
        user_id=u.id,
        name=name.strip(),
        imap_host=imap_host.strip(),
        imap_port=int(imap_port),
        imap_user=imap_user.strip(),
        imap_password_enc=encrypt_secret(imap_password),
        enabled=False,          # <-- zapis bez testu
        last_test_ok=None,      # <-- unknown
        last_test_error=None,   # <-- unknown
    )

    db.add(acc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        accounts = (
            db.query(MailAccount)
            .filter(MailAccount.user_id == u.id)
            .order_by(MailAccount.id.desc())
            .all()
        )
        return templates.TemplateResponse(
            "accounts.html",
            {
                "request": request,
                "user": u,
                "accounts": accounts,
                "error": "Could not add account (duplicate name?)",
            },
            status_code=400,
        )

    return RedirectResponse("/accounts", status_code=303)


@app.post("/accounts/toggle")
def accounts_toggle(
    request: Request,
    account_id: int = Form(...),
    db: Session = Depends(get_db),
):
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return RedirectResponse("/login", status_code=303)

    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)

    acc = (
        db.query(MailAccount)
        .filter(MailAccount.id == account_id, MailAccount.user_id == u.id)
        .first()
    )
    if not acc:
        return RedirectResponse("/accounts", status_code=303)

    # Enable attempt => run IMAP test
    if not bool(acc.enabled):
        try:
            plain_pw = decrypt_secret(acc.imap_password_enc)
            ok, err = imap_smoke_test(
                host=acc.imap_host,
                port=int(acc.imap_port),
                user=acc.imap_user,
                password=plain_pw,
            )
            acc.last_test_ok = ok
            acc.last_test_error = err
            acc.enabled = True if ok else False
        except Exception as exc:
            acc.enabled = False
            acc.last_test_ok = False
            acc.last_test_error = f"exception: {exc}"

        db.add(acc)
        db.commit()
        return RedirectResponse("/accounts", status_code=303)

    # Disable (no test)
    acc.enabled = False
    db.add(acc)
    db.commit()
    return RedirectResponse("/accounts", status_code=303)


# --- Email archive routes ---
@app.get("/emails", response_class=HTMLResponse)
def emails_list(
    request: Request,
    page: int = 1,
    per_page: int = 20,
    account_id: Optional[int] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Lista zarchiwizowanych maili"""
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()
    
    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)
    
    # Zapytanie bazowe
    query = db.query(ArchivedEmail).join(MailAccount).filter(
        MailAccount.user_id == u.id
    )
    
    # Filtry
    if account_id:
        query = query.filter(MailAccount.id == account_id)
    
    if q:
        q_like = f"%{q}%"
        query = query.filter(
            (ArchivedEmail.subject.ilike(q_like)) |
            (ArchivedEmail.sender.ilike(q_like)) |
            (ArchivedEmail.body_text.ilike(q_like))
        )
    
    # Paginacja
    total = query.count()
    emails = query.order_by(ArchivedEmail.date.desc()).offset(
        (page - 1) * per_page
    ).limit(per_page).all()
    
    # Statystyki
    stats = {
        "total_emails": db.query(func.count(ArchivedEmail.id))
                         .join(MailAccount)
                         .filter(MailAccount.user_id == u.id)
                         .scalar() or 0,
        "active_accounts": db.query(func.count(MailAccount.id))
                            .filter(MailAccount.user_id == u.id, 
                                    MailAccount.enabled == True)
                            .scalar() or 0,
        "total_accounts": db.query(func.count(MailAccount.id))
                           .filter(MailAccount.user_id == u.id)
                           .scalar() or 0,
        "with_attachments": db.query(func.count(ArchivedEmail.id))
                             .join(MailAccount)
                             .filter(MailAccount.user_id == u.id,
                                     ArchivedEmail.has_attachments == True)
                             .scalar() or 0,
        "last_sync": db.query(func.max(MailAccount.last_sync_at))
                       .filter(MailAccount.user_id == u.id)
                       .scalar()
    }
    
    # Lista kont do filtrowania
    accounts_list = db.query(MailAccount).filter(
        MailAccount.user_id == u.id
    ).all()
    
    selected_account_name = None
    if account_id:
        for acc in accounts_list:
            if acc.id == account_id:
                selected_account_name = acc.name
                break
    
    return templates.TemplateResponse(
        "emails.html",
        {
            "request": request,
            "user": u,
            "emails": emails,
            "accounts": accounts_list,
            "selected_account_id": account_id,
            "selected_account_name": selected_account_name,
            "query": q,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page if per_page > 0 else 1,
            "stats": stats
        }
    )


@app.get("/emails/{email_id}", response_class=HTMLResponse)
def email_detail(
    request: Request,
    email_id: int,
    db: Session = Depends(get_db)
):
    """Szczegóły maila"""
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)

    u = get_current_user(request, db)
    if not u:
        return redirect_login()
    
    if u.must_change_password:
        return RedirectResponse("/account/change-password", status_code=303)
    
    email = db.query(ArchivedEmail).join(MailAccount).filter(
        ArchivedEmail.id == email_id,
        MailAccount.user_id == u.id
    ).first()
    
    if not email:
        return RedirectResponse("/emails", status_code=303)
    
    return templates.TemplateResponse(
        "email_detail.html",
        {
            "request": request,
            "user": u,
            "email": email
        }
    )


## ========== API ENDPOINTS ==========
# Dodaj TUŻ przed końcem pliku, ale PRZED jeśli __name__ == "__main__"

@app.post("/api/sync/{account_id}")
async def api_sync_account(
    account_id: int,
    request: Request,
    db: Session = Depends(get_db)
):
    """Ręczna synchronizacja konta (POST)"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return {"error": "No admin setup"}
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return {"error": "Not authenticated"}
    
    uid = unsign_session(raw)
    if not uid:
        return {"error": "Invalid session"}
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return {"error": "User not found"}
    
    # Sprawdź uprawnienia
    account = db.query(MailAccount).filter(
        MailAccount.id == account_id,
        MailAccount.user_id == u.id
    ).first()
    
    if not account:
        return {"error": "Account not found"}
    
    if not account.enabled:
        return {"error": "Account is disabled"}
    
    # Uruchom w tle
    def sync_task():
        from .archive import EmailArchiver
        from .db import SessionLocal as LocalSession
        
        db_sync = LocalSession()
        try:
            archiver = EmailArchiver(account_id, db_sync)
            archiver.fetch_emails(since_days=30)
        finally:
            db_sync.close()
    
    thread = threading.Thread(target=sync_task)
    thread.daemon = True
    thread.start()
    
    return {"status": "started", "account_id": account_id, "account_name": account.name}


@app.post("/api/sync/all")
async def api_sync_all(
    request: Request,
    db: Session = Depends(get_db)
):
    """Synchronizuj wszystkie włączone konta (POST)"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return {"error": "No admin setup"}
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return {"error": "Not authenticated"}
    
    uid = unsign_session(raw)
    if not uid:
        return {"error": "Invalid session"}
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return {"error": "User not found"}
    
    # Pobierz włączone konta użytkownika
    accounts = db.query(MailAccount).filter(
        MailAccount.user_id == u.id,
        MailAccount.enabled == True
    ).all()
    
    if not accounts:
        return {"status": "no_enabled_accounts", "count": 0}
    
    # Uruchom w tle
    def sync_all_task():
        from .archive import sync_all_enabled_accounts
        sync_all_enabled_accounts()
    
    thread = threading.Thread(target=sync_all_task)
    thread.daemon = True
    thread.start()
    
    return {
        "status": "started", 
        "count": len(accounts),
        "accounts": [{"id": a.id, "name": a.name} for a in accounts]
    }


# ========== SIMPLE GET ENDPOINTS (dla linków) ==========
@app.get("/sync/all")
async def simple_sync_all(
    request: Request,
    db: Session = Depends(get_db)
):
    """Prosty endpoint GET do synchronizacji wszystkich kont"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return RedirectResponse("/login", status_code=303)
    
    uid = unsign_session(raw)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return RedirectResponse("/login", status_code=303)
    
    # Pobierz włączone konta użytkownika
    accounts = db.query(MailAccount).filter(
        MailAccount.user_id == u.id,
        MailAccount.enabled == True
    ).all()
    
    if not accounts:
        return RedirectResponse("/accounts?error=no_enabled_accounts", status_code=303)
    
    # Uruchom w tle
    def sync_all_task():
        from .archive import sync_all_enabled_accounts
        sync_all_enabled_accounts()
    
    thread = threading.Thread(target=sync_all_task)
    thread.daemon = True
    thread.start()
    
    return RedirectResponse(f"/accounts?sync_started=true&count={len(accounts)}", status_code=303)


@app.get("/sync/{account_id}")
async def simple_sync_account(
    request: Request,
    account_id: int,
    db: Session = Depends(get_db)
):
    """Prosty endpoint GET do synchronizacji pojedynczego konta"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return RedirectResponse("/login", status_code=303)
    
    uid = unsign_session(raw)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return RedirectResponse("/login", status_code=303)
    
    # Sprawdź uprawnienia
    account = db.query(MailAccount).filter(
        MailAccount.id == account_id,
        MailAccount.user_id == u.id
    ).first()
    
    if not account:
        return RedirectResponse("/accounts?error=account_not_found", status_code=303)
    
    if not account.enabled:
        return RedirectResponse("/accounts?error=account_disabled", status_code=303)
    
    # Uruchom w tle
    def sync_task():
        from .archive import EmailArchiver
        from .db import SessionLocal as LocalSession
        
        db_sync = LocalSession()
        try:
            archiver = EmailArchiver(account_id, db_sync)
            archiver.fetch_emails(since_days=30)
        finally:
            db_sync.close()
    
    thread = threading.Thread(target=sync_task)
    thread.daemon = True
    thread.start()
    
    return RedirectResponse(f"/accounts?sync_started=true&account={account.name}", status_code=303)

# --- Simple sync actions (POST forms) ---
@app.post("/sync-all-action")
async def sync_all_action(
    request: Request,
    db: Session = Depends(get_db)
):
    """Prosta akcja synchronizacji wszystkich kont (dla formularza)"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return RedirectResponse("/login", status_code=303)
    
    uid = unsign_session(raw)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return RedirectResponse("/login", status_code=303)
    
    # Pobierz włączone konta użytkownika
    accounts = db.query(MailAccount).filter(
        MailAccount.user_id == u.id,
        MailAccount.enabled == True
    ).all()
    
    if not accounts:
        return RedirectResponse("/accounts?error=no_enabled_accounts", status_code=303)
    
    # Uruchom w tle
    def sync_all_task():
        from .archive import sync_all_enabled_accounts
        sync_all_enabled_accounts()
    
    thread = threading.Thread(target=sync_all_task)
    thread.daemon = True
    thread.start()
    
    return RedirectResponse("/accounts?sync_started=true", status_code=303)


@app.post("/sync-account-action")
async def sync_account_action(
    request: Request,
    account_id: int = Form(...),  # Pobierz z formularza
    db: Session = Depends(get_db)
):
    """Prosta akcja synchronizacji pojedynczego konta (dla formularza)"""
    # Sprawdź czy admin istnieje
    if not has_admin(db):
        return RedirectResponse("/setup", status_code=303)
    
    # Pobierz użytkownika z sesji
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return RedirectResponse("/login", status_code=303)
    
    uid = unsign_session(raw)
    if not uid:
        return RedirectResponse("/login", status_code=303)
    
    u = db.query(User).filter(User.id == uid, User.is_active.is_(True)).first()
    if not u:
        return RedirectResponse("/login", status_code=303)
    
    # Sprawdź uprawnienia
    account = db.query(MailAccount).filter(
        MailAccount.id == account_id,
        MailAccount.user_id == u.id
    ).first()
    
    if not account:
        return RedirectResponse("/accounts?error=account_not_found", status_code=303)
    
    if not account.enabled:
        return RedirectResponse("/accounts?error=account_disabled", status_code=303)
    
    # Uruchom w tle
    def sync_task():
        from .archive import EmailArchiver
        from .db import SessionLocal as LocalSession
        
        db_sync = LocalSession()
        try:
            archiver = EmailArchiver(account_id, db_sync)
            archiver.fetch_emails(since_days=30)
        finally:
            db_sync.close()
    
    thread = threading.Thread(target=sync_task)
    thread.daemon = True
    thread.start()
    
    return RedirectResponse("/accounts?sync_started=true", status_code=303)