"""Email integration — master prompt §54.

Uses stdlib ``smtplib`` + ``imaplib`` (no extra deps). Secrets are loaded
via the credential manager:
- ``email_smtp_username`` / ``email_smtp_password`` (SMTP)
- ``email_imap_username`` / ``email_imap_password`` (IMAP)

Hosts/ports are read from env vars (``EMAIL_SMTP_HOST``, ``EMAIL_SMTP_PORT``,
``EMAIL_IMAP_HOST``, ``EMAIL_IMAP_PORT``) so they can be overridden per
deployment without touching the credential store.

When ``settings.mock_mode`` is True, all network calls are skipped and the
client returns deterministic fake data.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import get_credential, mask


# ---------------------------------------------------------------------------
# Pydantic model
# ---------------------------------------------------------------------------


class Email(BaseModel):
    """A single email message — normalised across SMTP/IMAP/Graph APIs."""

    id: str
    from_: str = Field(..., alias="from")
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    received_at: Optional[datetime] = None
    read: bool = False

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class EmailClient:
    """SMTP/IMAP email client.

    Mock-mode aware: when ``settings.mock_mode`` is True, ``send`` returns
    a fake success response without opening a socket, and ``receive_inbox``
    returns a small deterministic fixture.
    """

    def __init__(self) -> None:
        self.smtp_host = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "587"))
        self.imap_host = os.environ.get("EMAIL_IMAP_HOST", "imap.gmail.com")
        self.imap_port = int(os.environ.get("EMAIL_IMAP_PORT", "993"))

    # ---------- credential accessors (never log secrets) ----------

    @property
    def smtp_username(self) -> Optional[str]:
        return get_credential("email_smtp_username")

    @property
    def smtp_password(self) -> Optional[str]:
        return get_credential("email_smtp_password")

    @property
    def imap_username(self) -> Optional[str]:
        # Fall back to SMTP creds when IMAP-specific ones are absent
        return get_credential("email_imap_username") or self.smtp_username

    @property
    def imap_password(self) -> Optional[str]:
        return get_credential("email_imap_password") or self.smtp_password

    def is_configured(self) -> bool:
        """True if both SMTP username and password are present."""
        return bool(self.smtp_username) and bool(self.smtp_password)

    # ---------- public API ----------

    def send(self, to: str, subject: str, body: str, html: bool = False) -> dict:
        """Send a single email. ``to`` may be a comma-separated list.

        Returns ``{"sent": True, "to": [...]}`` on success.
        Raises ``RuntimeError`` if credentials are missing.
        """
        recipients = [r.strip() for r in to.split(",") if r.strip()]
        if not recipients:
            raise ValueError("At least one recipient is required")

        if settings.mock_mode:
            logger.info(
                "[mock] email send to={} subject={} from={}",
                recipients, subject, mask(self.smtp_username or "<none>"),
            )
            return {
                "sent": True,
                "to": recipients,
                "subject": subject,
                "mock": True,
            }

        if not self.is_configured():
            raise RuntimeError(
                "Email SMTP credentials are not configured — set "
                "EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD."
            )

        msg = MIMEMultipart("alternative") if html else MIMEText(body, "plain", "utf-8")
        if html:
            msg.attach(MIMEText(body, "plain", "utf-8"))
            msg.attach(MIMEText(body, "html", "utf-8"))
        msg["Subject"] = subject
        msg["From"] = self.smtp_username or ""
        msg["To"] = ", ".join(recipients)
        msg["Date"] = email.utils.formatdate(localtime=True)

        ctx = ssl.create_default_context()
        # Try STARTTLS first (port 587); fall back to SSL (port 465).
        try:
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx, timeout=30) as srv:
                    srv.login(self.smtp_username, self.smtp_password)
                    srv.sendmail(self.smtp_username, recipients, msg.as_string())
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30) as srv:
                    srv.ehlo()
                    srv.starttls(context=ctx)
                    srv.ehlo()
                    srv.login(self.smtp_username, self.smtp_password)
                    srv.sendmail(self.smtp_username, recipients, msg.as_string())
        except Exception as exc:
            logger.error("SMTP send failed: {}", exc)
            raise

        logger.info("Email sent to={} subject={}", recipients, subject)
        return {"sent": True, "to": recipients, "subject": subject}

    def receive_inbox(self, limit: int = 10) -> list[Email]:
        """Fetch the ``limit`` most recent INBOX messages.

        Returns a list of :class:`Email` objects (newest first).
        """
        if settings.mock_mode:
            return [
                Email(
                    id=f"mock-msg-{i}",
                    **{"from": "noreply@example.com"},
                    to=[self.smtp_username or "user@example.com"],
                    subject=f"Mock inbox message #{i}",
                    body=f"This is mock message #{i} — settings.mock_mode is on.",
                    received_at=datetime.now(timezone.utc),
                    read=False,
                )
                for i in range(min(limit, 5))
            ]

        if not (self.imap_username and self.imap_password):
            raise RuntimeError(
                "Email IMAP credentials are not configured — set "
                "EMAIL_IMAP_USERNAME and EMAIL_IMAP_PASSWORD."
            )

        ctx = ssl.create_default_context()
        out: list[Email] = []
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as srv:
                srv.login(self.imap_username, self.imap_password)
                srv.select("INBOX")
                # Fetch the last `limit` message sequence numbers
                typ, data = srv.search(None, "ALL")
                if typ != "OK":
                    raise RuntimeError(f"IMAP SEARCH failed: {typ}")
                ids = data[0].split()
                # newest first
                recent = list(reversed(ids))[:limit]
                for mid in recent:
                    typ, msg_data = srv.fetch(mid, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    parsed = email.message_from_bytes(raw)
                    body_text = _extract_body(parsed)
                    out.append(
                        Email(
                            id=mid.decode() if isinstance(mid, bytes) else str(mid),
                            **{"from": parsed.get("From", "")},
                            to=[parsed.get("To", "")],
                            subject=parsed.get("Subject", ""),
                            body=body_text,
                            received_at=_parse_date(parsed.get("Date")),
                            read=False,
                        )
                    )
        except Exception as exc:
            logger.error("IMAP fetch failed: {}", exc)
            raise
        return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_body(parsed: email.message.Message) -> str:
    """Extract the plain-text body of an email.message.Message."""
    if parsed.is_multipart():
        for part in parsed.walk():
            ctype = part.get_content_type()
            cdisp = str(part.get("Content-Disposition") or "")
            if ctype == "text/plain" and "attachment" not in cdisp:
                try:
                    payload = part.get_payload(decode=True)
                    if payload is not None:
                        return payload.decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        )
                except Exception:
                    continue
    else:
        try:
            payload = parsed.get_payload(decode=True)
            if payload is not None:
                return payload.decode(
                    parsed.get_content_charset() or "utf-8", errors="replace"
                )
        except Exception:
            pass
    return ""


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    try:
        tup = email.utils.parsedate_tz(date_str)
        if tup is None:
            return None
        ts = email.utils.mktime_tz(tup)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


__all__ = ["Email", "EmailClient"]
