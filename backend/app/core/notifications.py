"""
The three emails this app sends, and their copy.

1. **Verification code** — proves the address is reachable before a long job
   is allowed to start.
2. **Job started** — carries the tracking code, which is how the user gets
   back to their results later, from any browser.
3. **Job finished** (or failed) — tells them it is ready and links back.

The "come back later" link only ever prefills the tracking code, never the
email address: the two together are the credential pair that unlocks a job's
results (see app/core/tracking.py), and putting both in a URL would undo the
point of requiring both. The recipient types the address they just verified.

Sending is synchronous and best-effort. It is deliberately *not* pushed onto
the Celery queue: the same worker pool runs multi-hour TRUST4 assemblies, and
a verification code that waits behind one of those is worse than useless.
Every call returns a bool and swallows its own failures (see mailer.py), so a
mail outage degrades to "no email" rather than "no job".
"""

import logging
from urllib.parse import quote

from app.config import EMAIL_CODE_TTL, PUBLIC_APP_URL
from app.core.mailer import send_email

logger = logging.getLogger("app.notifications")

_SIGNATURE = "AIRR Preprocessor"


def format_duration(seconds: float) -> str:
    """Human-readable, deliberately coarse — these are rough estimates."""
    seconds = max(int(seconds), 0)
    if seconds < 90:
        return "less than a minute"
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"about {minutes} minutes"
    hours = seconds / 3600
    if hours < 2:
        return "about an hour"
    if hours < 24:
        return f"about {round(hours)} hours"
    return f"about {round(hours / 24)} days"


def format_size(num_bytes: int) -> str:
    mb = num_bytes / (1024 * 1024)
    if mb < 1024:
        return f"{mb:.0f} MB"
    return f"{mb / 1024:.1f} GB"


def tracking_url(tracking_code: str) -> str:
    """Link that opens the recovery page with the code already filled in."""
    return f"{PUBLIC_APP_URL}/track?code={quote(tracking_code)}"


def _wrap_html(title: str, body_html: str) -> str:
    """Minimal, inline-styled shell — email clients strip <style> blocks."""
    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:24px;background:#f4f6f8;
               font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
               color:#1c2733;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:12px;
                border:1px solid #e3e8ee;padding:28px;">
      <h1 style="margin:0 0 16px;font-size:18px;font-weight:600;">{title}</h1>
      {body_html}
      <p style="margin:28px 0 0;padding-top:16px;border-top:1px solid #e3e8ee;
                font-size:12px;color:#7a8899;">
        {_SIGNATURE} — this is an automated message, please do not reply.
      </p>
    </div>
  </body>
</html>"""


def _code_block(code: str) -> str:
    return (
        f'<p style="margin:20px 0;font-size:30px;font-weight:700;letter-spacing:6px;'
        f'text-align:center;color:#0f6fb8;">{code}</p>'
    )


def _button(url: str, label: str) -> str:
    return (
        f'<p style="margin:24px 0;"><a href="{url}" '
        f'style="display:inline-block;background:#0f6fb8;color:#ffffff;'
        f'text-decoration:none;padding:11px 20px;border-radius:8px;'
        f'font-size:14px;font-weight:600;">{label}</a></p>'
    )


# --- 1. Address verification ----------------------------------------------

def send_verification_code(email: str, code: str) -> bool:
    minutes = max(EMAIL_CODE_TTL // 60, 1)
    subject = f"{code} is your AIRR Preprocessor verification code"

    text = (
        f"Your verification code is: {code}\n\n"
        f"Enter it on the pipeline page to start your run. "
        f"The code expires in {minutes} minutes.\n\n"
        f"If you did not request this, you can ignore this email.\n\n"
        f"— {_SIGNATURE}\n"
    )

    html = _wrap_html(
        "Verify your email address",
        "<p style=\"margin:0;font-size:14px;line-height:1.6;\">"
        "Enter this code on the pipeline page to start your run:</p>"
        + _code_block(code)
        + f'<p style="margin:0;font-size:13px;color:#5a6b7d;line-height:1.6;">'
        f"The code expires in {minutes} minutes. "
        f"If you did not request it, you can ignore this email.</p>",
    )
    return send_email(email, subject, text, html)


# --- 2. Job accepted ------------------------------------------------------

def send_job_started(
    email: str,
    tracking_code: str,
    job_label: str,
    estimated_seconds: float | None = None,
) -> bool:
    subject = f"Your run has started — tracking code {tracking_code}"
    url = tracking_url(tracking_code)
    eta = (
        f"Estimated runtime: {format_duration(estimated_seconds)}.\n"
        if estimated_seconds
        else ""
    )

    text = (
        f"Your {job_label} run has started.\n\n"
        f"Tracking code: {tracking_code}\n"
        f"{eta}\n"
        f"You can close the page — we will email you when it finishes.\n"
        f"To check on it at any time, open {url} and enter this tracking code "
        f"together with this email address.\n\n"
        f"— {_SIGNATURE}\n"
    )

    eta_html = (
        f'<p style="margin:0 0 4px;font-size:14px;line-height:1.6;">'
        f"Estimated runtime: <strong>{format_duration(estimated_seconds)}</strong>.</p>"
        if estimated_seconds
        else ""
    )

    html = _wrap_html(
        "Your run has started",
        f'<p style="margin:0;font-size:14px;line-height:1.6;">'
        f"Your <strong>{job_label}</strong> run is now queued and processing.</p>"
        + eta_html
        + '<p style="margin:20px 0 0;font-size:13px;color:#5a6b7d;">'
        "Your tracking code</p>"
        + _code_block(tracking_code)
        + '<p style="margin:0;font-size:14px;line-height:1.6;">'
        "You can close the page — we will email you the moment it finishes.</p>"
        + _button(url, "Check on this run")
        + '<p style="margin:0;font-size:13px;color:#5a6b7d;line-height:1.6;">'
        "Opening that link asks for this email address as well as the code, "
        "so keep both to hand.</p>",
    )
    return send_email(email, subject, text, html)


# --- 3. Job finished ------------------------------------------------------

def send_job_finished(
    email: str,
    tracking_code: str,
    job_label: str,
    succeeded: bool,
    error: str | None = None,
) -> bool:
    url = tracking_url(tracking_code)

    if succeeded:
        subject = f"Your results are ready — tracking code {tracking_code}"
        text = (
            f"Your {job_label} run has finished successfully.\n\n"
            f"Tracking code: {tracking_code}\n\n"
            f"Open {url}, enter the tracking code and this email address, and "
            f"you will land back on your run with the results ready to "
            f"download.\n\n"
            f"— {_SIGNATURE}\n"
        )
        html = _wrap_html(
            "Your results are ready",
            f'<p style="margin:0;font-size:14px;line-height:1.6;">'
            f"Your <strong>{job_label}</strong> run finished successfully.</p>"
            + '<p style="margin:20px 0 0;font-size:13px;color:#5a6b7d;">'
            "Your tracking code</p>"
            + _code_block(tracking_code)
            + _button(url, "View my results")
            + '<p style="margin:0;font-size:13px;color:#5a6b7d;line-height:1.6;">'
            "You will be asked for the tracking code and this email address.</p>",
        )
    else:
        subject = f"Your run did not finish — tracking code {tracking_code}"
        detail = f"\nWhat went wrong: {error}\n" if error else ""
        text = (
            f"Your {job_label} run stopped before it finished.\n"
            f"{detail}\n"
            f"Tracking code: {tracking_code}\n\n"
            f"Open {url} and enter the tracking code and this email address to "
            f"see the full details and which step it stopped at.\n\n"
            f"— {_SIGNATURE}\n"
        )
        detail_html = (
            f'<p style="margin:12px 0 0;padding:12px;background:#fdf0f0;'
            f'border-radius:8px;font-size:13px;color:#9b2c2c;line-height:1.6;">'
            f"{error}</p>"
            if error
            else ""
        )
        html = _wrap_html(
            "Your run did not finish",
            f'<p style="margin:0;font-size:14px;line-height:1.6;">'
            f"Your <strong>{job_label}</strong> run stopped before it "
            f"finished.</p>"
            + detail_html
            + '<p style="margin:20px 0 0;font-size:13px;color:#5a6b7d;">'
            "Your tracking code</p>"
            + _code_block(tracking_code)
            + _button(url, "See what happened"),
        )

    return send_email(email, subject, text, html)
