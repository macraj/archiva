from datetime import datetime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import String, Integer, Boolean, DateTime, ForeignKey, Text, UniqueConstraint

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="user")  # user/admin
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    mail_accounts: Mapped[list["MailAccount"]] = relationship(back_populates="owner")

class MailAccount(Base):
    __tablename__ = "mail_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_user_account_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(80))
    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_user: Mapped[str] = mapped_column(String(255))
    imap_password_enc: Mapped[str] = mapped_column(Text)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    owner: Mapped["User"] = relationship(back_populates="mail_accounts")

