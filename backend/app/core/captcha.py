"""
A small self-hosted CAPTCHA.

Deliberately not hCaptcha/reCAPTCHA/Turnstile: those need an account, an API
key, and an outbound call to a third party on every check — a lot of moving
parts for a service whose whole job is to stop a script hammering two
endpoints. This generates its own challenge, renders it as an SVG, and
verifies it against Redis. No dependency, no external service, nothing to
sign up for.

It is a speed bump, not a wall. A determined attacker with an OCR pipeline
gets through; that is true of every image CAPTCHA. What it does stop is the
cheap case — a loop hitting the endpoint directly — and it works alongside
the existing per-IP rate limits rather than replacing them.

The answer is stored hashed and the challenge is destroyed on first use, so a
solved challenge cannot be replayed and a wrong guess cannot be retried
against the same image.

**Accessibility:** this is an image-only challenge, so it is not usable by
someone relying on a screen reader. It guards two routes, both of which have
an alternative path (a user can reach their results from the tab that
started the run without ever going through /track). If that stops being true,
this needs an audio or logic-question alternative.
"""

import base64
import hashlib
import hmac
import random
import secrets
import string
from dataclasses import dataclass

from app.config import CAPTCHA_LENGTH, CAPTCHA_TTL, redis_client

# No 0/O, 1/I/L, 5/S, 2/Z — the pairs people misread, which turn a working
# CAPTCHA into a support ticket.
_ALPHABET = "".join(
    c for c in string.ascii_uppercase + string.digits
    if c not in "0O1IL5S2Z"
)

_WIDTH, _HEIGHT = 160, 56


class CaptchaError(Exception):
    """Raised when a challenge is missing, expired, or answered wrongly."""


@dataclass
class Challenge:
    captcha_id: str
    #: `data:image/svg+xml;base64,...` — ready to drop into an <img src>.
    image: str
    expires_in: int


def _key(captcha_id: str) -> str:
    return f"captcha:{captcha_id}"


def _hash_answer(captcha_id: str, answer: str) -> str:
    # Salted with the id so identical answers across challenges do not share
    # a hash.
    normalized = (answer or "").strip().upper()
    return hashlib.sha256(f"{captcha_id}:{normalized}".encode("utf-8")).hexdigest()


def _render_svg(text: str) -> str:
    """Draw the text distorted enough that naive OCR struggles."""
    rng = random.SystemRandom()
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_WIDTH}" '
        f'height="{_HEIGHT}" viewBox="0 0 {_WIDTH} {_HEIGHT}" '
        f'role="img" aria-label="CAPTCHA">',
        f'<rect width="{_WIDTH}" height="{_HEIGHT}" fill="#f1f5f9"/>',
    ]

    # Noise behind the glyphs: curves that cross them, so a bot cannot simply
    # threshold the image and read connected components.
    for _ in range(4):
        x1, y1 = rng.randint(0, 20), rng.randint(0, _HEIGHT)
        x2, y2 = rng.randint(_WIDTH - 20, _WIDTH), rng.randint(0, _HEIGHT)
        cx, cy = rng.randint(30, _WIDTH - 30), rng.randint(-10, _HEIGHT + 10)
        shade = rng.randint(140, 190)
        parts.append(
            f'<path d="M{x1} {y1} Q{cx} {cy} {x2} {y2}" fill="none" '
            f'stroke="rgb({shade},{shade},{shade})" stroke-width="1.5"/>'
        )

    step = _WIDTH / (len(text) + 1)
    for index, char in enumerate(text):
        x = step * (index + 1)
        y = _HEIGHT / 2 + rng.randint(-4, 4)
        rotation = rng.randint(-28, 28)
        size = rng.randint(26, 32)
        r, g, b = (rng.randint(20, 90) for _ in range(3))
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'font-family="Georgia,serif" font-weight="bold" '
            f'fill="rgb({r},{g},{b})" text-anchor="middle" '
            f'dominant-baseline="middle" '
            f'transform="rotate({rotation} {x:.1f} {y:.1f})">{char}</text>'
        )

    # A few dots on top, so the glyphs are not the only foreground.
    for _ in range(18):
        parts.append(
            f'<circle cx="{rng.randint(0, _WIDTH)}" '
            f'cy="{rng.randint(0, _HEIGHT)}" r="{rng.randint(1, 2)}" '
            f'fill="rgb({rng.randint(120,180)},{rng.randint(120,180)},'
            f'{rng.randint(120,180)})"/>'
        )

    parts.append("</svg>")
    return "".join(parts)


def new_challenge() -> Challenge:
    """Create a challenge and return it with the answer already stored."""
    captcha_id = secrets.token_urlsafe(16)
    answer = "".join(secrets.choice(_ALPHABET) for _ in range(CAPTCHA_LENGTH))

    redis_client.set(_key(captcha_id), _hash_answer(captcha_id, answer),
                     ex=CAPTCHA_TTL)

    svg = _render_svg(answer)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")

    return Challenge(
        captcha_id=captcha_id,
        image=f"data:image/svg+xml;base64,{encoded}",
        expires_in=CAPTCHA_TTL,
    )


def verify(captcha_id: str, answer: str) -> None:
    """
    Check an answer and consume the challenge. Raises CaptchaError on any
    failure.

    The challenge is deleted whether or not the answer was right: letting a
    wrong answer be retried against the same image would turn a 5-character
    CAPTCHA into something a script can simply guess at.
    """
    from app.config import CAPTCHA_ENABLED

    if not CAPTCHA_ENABLED:
        return

    if not captcha_id or not answer:
        raise CaptchaError("Please complete the anti-bot check.")

    key = _key(captcha_id)
    expected = redis_client.get(key)
    redis_client.delete(key)

    if not expected:
        raise CaptchaError("That check expired. Please try the new image.")

    if not hmac.compare_digest(_hash_answer(captcha_id, answer), expected):
        raise CaptchaError("Those characters did not match. Please try again.")
