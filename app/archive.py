import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import json
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from sqlalchemy.orm import Session

from .models import MailAccount, ArchivedEmail
from .security import decrypt_secret
from .db import SessionLocal

logger = logging.getLogger(__name__)


class EmailArchiver:
    def __init__(self, account_id: int, db: Session):
        self.account_id = account_id
        self.db = db
        self.account: Optional[MailAccount] = None
        self.imap: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        """Nawiązanie połączenia IMAP"""
        self.account = (
            self.db.query(MailAccount)
            .filter(MailAccount.id == self.account_id, MailAccount.enabled == True)
            .first()
        )
        if not self.account:
            logger.error(f"Account {self.account_id} not found or disabled")
            return False

        try:
            password = decrypt_secret(self.account.imap_password_enc)
            self.imap = imaplib.IMAP4_SSL(self.account.imap_host, self.account.imap_port)
            self.imap.login(self.account.imap_user, password)
            logger.info(f"Connected to {self.account.imap_user}@{self.account.imap_host}")
            return True
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            self.account.last_sync_status = "failed"
            self.account.last_sync_error = str(e)
            self.db.commit()
            return False

    def fetch_emails(self, batch_size: int = 500) -> int:
        """
        Pierwsza synchronizacja: ALL (wszystkie maile) i batchowanie.
        Kolejne: SINCE od last_sync_at (dokładność do dnia po stronie IMAP).
        """
        if not self.connect():
            return 0

        try:
            assert self.imap is not None
            assert self.account is not None

            self.imap.select("INBOX")

            if self.account.last_sync_at is None:
                search_criteria = "ALL"
                logger.info("First sync -> using IMAP search: ALL")
            else:
                since_date = self.account.last_sync_at.strftime("%d-%b-%Y")
                search_criteria = f'(SINCE "{since_date}")'
                logger.info(f"Next sync -> using IMAP search: {search_criteria}")

            status, messages = self.imap.search(None, search_criteria)
            if status != "OK":
                logger.error("Search failed")
                return 0

            email_ids = messages[0].split()
            total = len(email_ids)
            logger.info(f"IMAP search returned {total} ids")

            fetched_total = 0

            # Batchowanie: od początku listy (zwykle najstarsze -> najnowsze)
            for start in range(0, total, batch_size):
                batch = email_ids[start : start + batch_size]
                logger.info(f"Processing batch {start}..{start+len(batch)-1} ({len(batch)} emails)")

                for email_id in batch:
                    if self._fetch_single_email(email_id):
                        fetched_total += 1

                # checkpoint statusu konta po batchu (na wypadek przerwania)
                self.account.last_sync_status = "partial"
                self.db.commit()

            # finalny update statusu
            self.account.last_sync_at = datetime.utcnow()
            self.account.last_sync_status = "success" if fetched_total > 0 else "partial"
            self.account.emails_count += fetched_total
            self.account.last_sync_error = None
            self.db.commit()

            return fetched_total

        except Exception as e:
            logger.error(f"Fetch failed: {e}")
            if self.account is not None:
                self.account.last_sync_status = "failed"
                self.account.last_sync_error = str(e)
                self.db.commit()
            return 0

        finally:
            if self.imap:
                try:
                    self.imap.logout()
                except Exception:
                    pass

    def _fetch_single_email(self, email_id: bytes) -> bool:
        """Pobierz i zapisz pojedynczy email"""
        try:
            assert self.imap is not None

            status, msg_data = self.imap.fetch(email_id, "(RFC822)")
            if status != "OK":
                return False

            email_body = msg_data[0][1]
            msg = email.message_from_bytes(email_body)

            # Sprawdź czy email już istnieje
            message_id = msg.get("Message-ID", f"unknown-{email_id.decode()}")
            existing = (
                self.db.query(ArchivedEmail)
                .filter(ArchivedEmail.message_id == message_id)
                .first()
            )
            if existing:
                logger.debug(f"Email {message_id} already archived")
                return False

            sender = self._decode_header(msg.get("From", ""))
            subject = self._decode_header(msg.get("Subject", ""))

            # Parsuj datę
            date_str = msg.get("Date")
            email_date = None
            if date_str:
                try:
                    email_date = parsedate_to_datetime(date_str)
                except Exception:
                    pass

            body_text = None
            body_html = None
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition"))

                    if "attachment" in content_disposition:
                        attachment_info = self._save_attachment(part)
                        if attachment_info:
                            attachments.append(attachment_info)

                    elif content_type == "text/plain" and not body_text:
                        body_text = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="ignore"
                        )

                    elif content_type == "text/html" and not body_html:
                        body_html = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", errors="ignore"
                        )
            else:
                body_text = msg.get_payload(decode=True).decode(
                    msg.get_content_charset() or "utf-8", errors="ignore"
                )

            archived = ArchivedEmail(
                account_id=self.account_id,
                message_id=message_id,
                sender=sender,
                recipients=msg.get("To", ""),
                subject=subject,
                date=email_date or datetime.utcnow(),
                body_text=body_text[:50000] if body_text else None,
                body_html=body_html[:50000] if body_html else None,
                attachments_json=json.dumps(attachments) if attachments else None,
                has_attachments=len(attachments) > 0,
                raw_headers=str(msg.items()),
            )

            self.db.add(archived)
            self.db.commit()

            logger.info(f"Archived email: {subject[:50]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to archive email {email_id}: {e}")
            self.db.rollback()
            return False

    def _decode_header(self, header: str) -> str:
        """Dekoduj nagłówki e-mail"""
        try:
            decoded_parts = decode_header(header)
            result = []
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    result.append(part.decode(encoding or "utf-8", errors="ignore"))
                else:
                    result.append(str(part))
            return " ".join(result)
        except Exception:
            return str(header)

    def _save_attachment(self, part) -> Optional[Dict[str, Any]]:
        """Zapisz załącznik (wersja podstawowa - metadane)"""
        filename = part.get_filename()
        if filename:
            decoded_filename = self._decode_header(filename)
            return {
                "filename": decoded_filename,
                "content_type": part.get_content_type(),
                "size": len(part.get_payload(decode=True) or b""),
                "saved": False,
            }
        return None


def sync_account(account_id: int) -> Dict[str, Any]:
    """Synchronizuj pojedyncze konto"""
    db = SessionLocal()
    try:
        archiver = EmailArchiver(account_id, db)
        count = archiver.fetch_emails(batch_size=500)
        return {"account_id": account_id, "fetched": count, "success": True}
    finally:
        db.close()


def sync_all_enabled_accounts() -> Dict[str, Any]:
    """Synchronizuj wszystkie włączone konta"""
    db = SessionLocal()
    try:
        accounts = db.query(MailAccount).filter(MailAccount.enabled == True).all()
        results = []

        for account in accounts:
            try:
                result = sync_account(account.id)
                results.append(result)
            except Exception as e:
                results.append(
                    {"account_id": account.id, "fetched": 0, "success": False, "error": str(e)}
                )

        return {
            "total": len(accounts),
            "successful": sum(1 for r in results if r.get("success")),
            "failed": sum(1 for r in results if not r.get("success")),
            "results": results,
        }
    finally:
        db.close()
