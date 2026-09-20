"""
SMTP transport for the notification emails.

Deliberately dependency-free (stdlib ``smtplib``) so it works against any
provider the deployment happens to have: a company mail server, a Gmail
app-password account, SendGrid/Mailgun's SMTP endpoints. All of it is
configured through the SMTP_* environment variables in app/config.py.

Two properties everything else in the codebase relies on:

* **Sending never raises.** A mail server being down must not fail a job
  start or lose a finished job's results, so ``send_email`` reports success
  as a bool and logs the failure instead of propagating it. Callers decide
  what (if anything) that means for the user.
* **Unconfigured is a valid state.** With SMTP_HOST empty the message is
  written to the log instead of sent, which makes the whole verify → start →
  finish flow — including reading the 6-digit code — testable locally with
  no mail server at all.
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.config import (
    MAIL_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SECURITY,
    SMTP_TIMEOUT,
    SMTP_USER,
)

logger = logging.getLogger("app.mailer")


def is_configured() -> bool:
    """Whether a real mail server is available (vs. the log-only fallback)."""
    return bool(SMTP_HOST)


def _build_message(to: str, subject: str, text_body: str, html_body: str | None):
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = MAIL_FROM
    message["To"] = to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    return message


def _deliver(message: EmailMessage) -> None:
    """Open a connection, send one message, close. Raises on failure."""
    if SMTP_SECURITY == "ssl":
        context = ssl.create_default_context()
        smtp = smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=context
        )
    else:
        smtp = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)

    with smtp:
        if SMTP_SECURITY == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if SMTP_USER:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
        smtp.send_message(message)


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> bool:
    """
    Send one email. Returns True if it was handed to the mail server (or
    logged, when no server is configured), False if delivery failed.

    Never raises — see the module docstring.
    """
    if not is_configured():
        logger.warning(
            "SMTP is not configured (SMTP_HOST is empty); email not sent.\n"
            "--- would have sent ---\nTo: %s\nSubject: %s\n\n%s\n"
            "--- end ---",
            to,
            subject,
            text_body,
        )
        return True

    try:
        _deliver(_build_message(to, subject, text_body, html_body))
    except Exception:
        # Full traceback to the server log; callers only ever see False.
        logger.error("Failed to send email to %s (%r)", to, subject, exc_info=True)
        return False

    logger.info("Sent email to %s (%r)", to, subject)
    return True
