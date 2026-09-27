"""Outgoing email from info@blockid.au (Google Workspace).

Configured by env (in /opt/blockid/app.env):
  SMTP_HOST      smtp.gmail.com (App Password) or smtp-relay.gmail.com (Workspace SMTP relay, IP allow-list)
  SMTP_PORT      587 (STARTTLS, default) or 465 (implicit TLS)
  SMTP_USER      info@blockid.au (empty for the IP-authenticated relay)
  SMTP_PASSWORD  Google App Password of info@blockid.au (empty for the relay)
  MAIL_FROM      "BlockID <info@blockid.au>"
Replies go to MAIL_REPLY_TO (default info@blockid.au), so inbound mail lands in the same Workspace inbox.
Nothing is sent when SMTP_HOST is empty; callers treat mail as best effort.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

log = logging.getLogger(__name__)


def _env(k: str, d: str = "") -> str:
    return os.environ.get(k, d).strip()


# last outcomes of real send attempts in this process (any mail: welcome, test, ops) -> ops "email.delivery" check
RECENT: list[tuple[float, bool, str | None]] = []


def _record(ok: bool, error: str | None) -> None:
    import time

    RECENT.append((time.time(), ok, error))
    del RECENT[:-20]


class Mailer:
    def __init__(self) -> None:
        self.host = _env("SMTP_HOST")
        self.port = int(_env("SMTP_PORT", "587") or 587)
        self.user = _env("SMTP_USER")
        self.password = _env("SMTP_PASSWORD")
        self.sender = _env("MAIL_FROM", formataddr(("BlockID Business Passport", "info@blockid.au")))
        self.reply_to = _env("MAIL_REPLY_TO", "info@blockid.au")
        self.last_error: str | None = None  # why the last send() returned False (ops email-delivery check)

    @property
    def configured(self) -> bool:
        return bool(self.host)

    def build(self, to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
        m = EmailMessage()
        m["From"], m["To"], m["Subject"], m["Reply-To"] = self.sender, to, subject, self.reply_to
        m["Message-ID"] = make_msgid(domain="blockid.au")
        m.set_content(text)
        if html:
            m.add_alternative(html, subtype="html")
        return m

    def send(self, to: str, subject: str, text: str, html: str | None = None) -> bool:
        if not self.configured:
            log.info("mail not configured; skipped %r to %s", subject, to)
            self.last_error = "SMTP not configured"
            return False
        msg = self.build(to, subject, text, html)
        ctx = ssl.create_default_context()
        try:
            if self.port == 465:
                with smtplib.SMTP_SSL(self.host, self.port, context=ctx, timeout=15) as smtp:
                    self._deliver(smtp, msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
                    smtp.ehlo("eth.blockid.au")
                    smtp.starttls(context=ctx)
                    smtp.ehlo("eth.blockid.au")
                    self._deliver(smtp, msg)
            self.last_error = None
            _record(True, None)
            return True
        except Exception as e:  # noqa: BLE001 - best effort, logged
            log.warning("mail to %s failed: %s", to, e)
            self.last_error = f"{type(e).__name__}: {e}"[:300]
            _record(False, self.last_error)
            return False

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.user and self.password:
            smtp.login(self.user, self.password)
        smtp.send_message(msg)


def welcome(name: str | None, address: str, lang: str = "en") -> tuple[str, str, str]:
    """(subject, text, html) for the first Google sign-in."""
    who = name or ("there" if lang == "en" else "bạn")
    if lang == "vi":
        subject = "Chào mừng đến BlockID Business Passport"
        text = (f"Chào {who},\n\nTài khoản của bạn đã sẵn sàng. Địa chỉ ví của bạn:\n{address}\n\n"
                "Khoá riêng của ví được tạo và lưu ngay trên trình duyệt của bạn. BlockID không giữ khoá này. "
                "Hãy vào Tài khoản > Sao lưu khoá để lưu một bản dự phòng.\n\n"
                "Xem danh mục của bạn: https://eth.blockid.au/i\n\n"
                "Bản demo trên testnet. Không phải chào bán chứng khoán hay tư vấn tài chính.\n"
                "Cần hỗ trợ? Trả lời email này hoặc viết cho info@blockid.au.")
    else:
        subject = "Welcome to BlockID Business Passport"
        text = (f"Hi {who},\n\nYour account is ready. Your wallet address:\n{address}\n\n"
                "The private key for this wallet was created and is stored in your browser. BlockID never holds it. "
                "Go to Account > Back up key to keep a copy somewhere safe.\n\n"
                "See your holdings: https://eth.blockid.au/i\n\n"
                "Testnet demo. Not an offer of securities or financial advice.\n"
                "Questions? Reply to this email or write to info@blockid.au.")
    html = "<div style=\"font-family:system-ui,sans-serif;font-size:15px;line-height:1.55;color:#10262B\">" + "".join(
        f"<p>{p.replace(chr(10), '<br>')}</p>" for p in text.split("\n\n")) + "</div>"
    return subject, text, html
