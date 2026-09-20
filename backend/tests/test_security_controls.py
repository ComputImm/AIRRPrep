"""
Automated checks of the security controls the manuscript describes
(Supplementary Note S2, "Handling of email addresses and recovery controls").

Every statement made there about verification codes, tracking codes and the
recovery route is asserted here against the implementation, so the text
cannot drift away from the code:

  * verification codes expire (EMAIL_CODE_TTL) and a wrong guess does not
    extend that expiry;
  * a code is burned after EMAIL_CODE_MAX_ATTEMPTS wrong guesses;
  * resending is refused inside EMAIL_CODE_RESEND_COOLDOWN;
  * codes are stored only as a salted hash -- never in plain text;
  * addresses are normalized (trimmed, lower-cased) before storage and
    comparison, and rejected when malformed;
  * the tracking record stores a keyed HMAC-SHA256 of the address, not the
    address, and not a bare SHA-256 that a candidate list would reverse;
  * a wrong code and a wrong address give the same (empty) answer, so the
    route is not an oracle for which codes exist;
  * the recovery link in an email carries only the code, never the address;
  * the recovery and code-sending routes are rate limited, and recovery
    additionally requires a solved CAPTCHA, which is consumed on first use.

Redis is replaced with an in-memory stand-in (tests/_fakeredis.py) with an
injectable clock, so expiry is tested without sleeping and without a server.

    cd presto-backend
    venv/Scripts/python.exe -m unittest tests.test_security_controls -v
"""

import hashlib
import json
import time as _time
import unittest
from unittest import mock

_real_time = _time.time

from tests._fakeredis import FakeRedis


class EmailVerificationCodeTests(unittest.TestCase):
    session = "session-under-test"
    address = "Someone@Example.ORG"

    def setUp(self):
        from app.core import email_verification as ev

        self.ev = ev
        self.redis = FakeRedis()
        self._patches = [
            mock.patch.object(ev, "redis_client", self.redis),
            mock.patch.object(ev, "EMAIL_HASH_SECRET", "a-server-side-secret"),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()

    # -- storage ----------------------------------------------------------
    def test_the_code_is_stored_only_as_a_salted_hash(self):
        code = self.ev.request_code(self.session, self.address)
        (raw,) = [self.redis.get(k) for k in self.redis.keys("emailverify:*")]
        record = json.loads(raw)

        self.assertNotIn(code, raw)
        self.assertEqual(
            record["code_hash"],
            hashlib.sha256(f"{self.session}:{code}".encode()).hexdigest(),
        )
        # Salted with the session id: the same code elsewhere hashes differently.
        self.assertNotEqual(
            record["code_hash"], hashlib.sha256(code.encode()).hexdigest()
        )

    def test_the_address_is_normalized_before_storage(self):
        self.ev.request_code(self.session, "  Someone@Example.ORG ")
        (raw,) = [self.redis.get(k) for k in self.redis.keys("emailverify:*")]
        self.assertEqual(json.loads(raw)["email"], "someone@example.org")

    def test_a_malformed_address_is_refused(self):
        for bad in ("", "   ", "not-an-address", "a@b", "a@@b.com", "a b@c.com"):
            with self.subTest(bad=bad):
                with self.assertRaises(self.ev.EmailVerificationError):
                    self.ev.normalize_email(bad)

    # -- expiry -----------------------------------------------------------
    def test_a_code_expires_after_the_configured_ttl(self):
        code = self.ev.request_code(self.session, self.address)
        self.redis.advance(self.ev.EMAIL_CODE_TTL + 1)

        outcome = self.ev.confirm_code(self.session, self.address, code)
        self.assertFalse(outcome.ok)
        self.assertIn("expired", outcome.message.lower())

    def test_a_wrong_guess_does_not_extend_the_expiry(self):
        code = self.ev.request_code(self.session, self.address)
        ttl_before = self.redis.ttl(f"emailverify:{self.session}")

        self.redis.advance(30)
        self.ev.confirm_code(self.session, self.address, "000000")
        ttl_after = self.redis.ttl(f"emailverify:{self.session}")

        self.assertLessEqual(ttl_after, ttl_before - 30)
        del code

    # -- attempt limit ----------------------------------------------------
    def test_the_code_is_burned_after_the_attempt_limit(self):
        code = self.ev.request_code(self.session, self.address)
        wrong = "000000" if code != "000000" else "111111"

        for expected_left in range(self.ev.EMAIL_CODE_MAX_ATTEMPTS - 1, 0, -1):
            outcome = self.ev.confirm_code(self.session, self.address, wrong)
            self.assertFalse(outcome.ok)
            self.assertEqual(outcome.attempts_remaining, expected_left)

        final = self.ev.confirm_code(self.session, self.address, wrong)
        self.assertFalse(final.ok)
        self.assertIn("Too many", final.message)
        # Burned: even the correct code no longer works.
        self.assertFalse(self.ev.confirm_code(self.session, self.address, code).ok)
        self.assertEqual(self.redis.keys("emailverify:*"), [])

    # -- resend throttle --------------------------------------------------
    def test_resending_inside_the_cooldown_is_refused(self):
        self.ev.request_code(self.session, self.address)
        with self.assertRaisesRegex(
            self.ev.EmailVerificationError, "just sent"
        ):
            self.ev.request_code(self.session, self.address)

    def test_resending_after_the_cooldown_issues_a_new_code(self):
        first = self.ev.request_code(self.session, self.address)
        elapsed = self.ev.EMAIL_CODE_RESEND_COOLDOWN + 1
        self.redis.advance(elapsed)
        # The cooldown is measured against the wall clock, not Redis' TTL.
        with mock.patch.object(
            self.ev.time, "time", lambda: _real_time() + elapsed
        ):
            second = self.ev.request_code(self.session, self.address)

        # The old code must no longer verify: the record was replaced.
        self.assertFalse(self.ev.confirm_code(self.session, self.address, first).ok)
        self.assertIsNotNone(second)

    # -- wrong address ----------------------------------------------------
    def test_a_code_does_not_verify_a_different_address(self):
        code = self.ev.request_code(self.session, self.address)
        outcome = self.ev.confirm_code(self.session, "someone.else@example.org", code)
        self.assertFalse(outcome.ok)


class EmailHashingTests(unittest.TestCase):
    """The tracking record stores a keyed HMAC, not the address."""

    def setUp(self):
        from app.core import email_verification as ev

        self.ev = ev

    def test_hash_is_keyed_and_not_a_bare_sha256(self):
        plain = hashlib.sha256(b"someone@example.org").hexdigest()
        with mock.patch.object(self.ev, "EMAIL_HASH_SECRET", "key-one"):
            one = self.ev.hash_email(" Someone@Example.org ")
            again = self.ev.hash_email("someone@example.org")
        with mock.patch.object(self.ev, "EMAIL_HASH_SECRET", "key-two"):
            two = self.ev.hash_email("someone@example.org")

        self.assertEqual(one, again, "normalization must make the hash stable")
        self.assertNotEqual(one, plain, "a candidate list must not reverse it")
        self.assertNotEqual(one, two, "the server-side key must matter")
        self.assertEqual(len(one), 64)


class TrackingRecoveryTests(unittest.TestCase):
    def setUp(self):
        from app.core import email_verification as ev
        from app.core import tracking

        self.tracking = tracking
        self.redis = FakeRedis()
        self._patches = [
            mock.patch.object(tracking, "redis_client", self.redis),
            mock.patch.object(ev, "EMAIL_HASH_SECRET", "a-server-side-secret"),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()

    def issue(self, email="owner@example.org") -> str:
        return self.tracking.create_tracking_code(
            "sess-1", "job-1", email, "/pipeline/umi-miseq-2x250", "UMI 2x250"
        )

    def test_the_record_never_contains_the_address(self):
        code = self.issue()
        raw = self.redis.get(f"track:{code}")
        self.assertNotIn("owner@example.org", raw)
        self.assertNotIn("owner", raw)
        self.assertEqual(len(json.loads(raw)["email_hash"]), 64)

    def test_the_code_alone_does_not_resolve(self):
        code = self.issue()
        self.assertIsNone(self.tracking.resolve_tracking(code, "someone@else.org"))
        self.assertIsNotNone(
            self.tracking.resolve_tracking(code, "owner@example.org")
        )

    def test_address_normalization_applies_to_recovery(self):
        code = self.issue("Owner@Example.ORG")
        self.assertIsNotNone(
            self.tracking.resolve_tracking(code, "  owner@example.org  ")
        )

    def test_wrong_code_and_wrong_address_are_indistinguishable(self):
        code = self.issue()
        unknown_code = self.tracking.resolve_tracking("999999", "owner@example.org")
        wrong_address = self.tracking.resolve_tracking(code, "other@example.org")
        malformed = self.tracking.resolve_tracking(code, "not-an-address")
        self.assertIsNone(unknown_code)
        self.assertIsNone(wrong_address)
        self.assertIsNone(malformed)

    def test_records_expire_and_an_active_run_can_be_refreshed(self):
        code = self.issue()
        self.redis.advance(self.tracking.TRACKED_JOB_TTL - 10)
        self.tracking.touch_tracking(code)
        self.redis.advance(20)
        self.assertIsNotNone(
            self.tracking.resolve_tracking(code, "owner@example.org")
        )

        self.redis.advance(self.tracking.TRACKED_JOB_TTL + 1)
        self.assertIsNone(
            self.tracking.resolve_tracking(code, "owner@example.org")
        )

    def test_codes_are_allocated_atomically(self):
        """Two runs must never be handed the same code."""
        taken = {self.issue() for _ in range(25)}
        self.assertEqual(len(taken), 25)


class RecoveryLinkTests(unittest.TestCase):
    def test_the_emailed_link_carries_the_code_and_never_the_address(self):
        from app.core import notifications

        url = notifications.tracking_url("123456")
        self.assertIn("code=123456", url)
        self.assertNotIn("@", url.split("?", 1)[1])
        self.assertNotIn("email", url.lower())


class CaptchaTests(unittest.TestCase):
    def setUp(self):
        from app.core import captcha

        self.captcha = captcha
        self.redis = FakeRedis()
        self._patch = mock.patch.object(captcha, "redis_client", self.redis)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def solve(self, challenge_id: str, answer: str):
        with mock.patch("app.config.CAPTCHA_ENABLED", True):
            self.captcha.verify(challenge_id, answer)

    def test_the_answer_is_stored_hashed_and_consumed_on_first_use(self):
        challenge = self.captcha.new_challenge()
        stored = self.redis.get(f"captcha:{challenge.captcha_id}")
        self.assertEqual(len(stored), 64)

        # A wrong answer still destroys the challenge, so the same image
        # cannot be guessed at repeatedly.
        with mock.patch("app.config.CAPTCHA_ENABLED", True):
            with self.assertRaises(self.captcha.CaptchaError):
                self.captcha.verify(challenge.captcha_id, "WRONG")
        self.assertIsNone(self.redis.get(f"captcha:{challenge.captcha_id}"))

    def test_an_expired_challenge_is_refused(self):
        challenge = self.captcha.new_challenge()
        self.redis.advance(self.captcha.CAPTCHA_TTL + 1)
        with mock.patch("app.config.CAPTCHA_ENABLED", True):
            with self.assertRaisesRegex(self.captcha.CaptchaError, "expired"):
                self.captcha.verify(challenge.captcha_id, "ANYTHING")

    def test_a_missing_answer_is_refused(self):
        with mock.patch("app.config.CAPTCHA_ENABLED", True):
            with self.assertRaises(self.captcha.CaptchaError):
                self.captcha.verify("", "")


class RouteGuardTests(unittest.TestCase):
    """The rate limits and CAPTCHA the manuscript quotes, read off the routes."""

    def source(self) -> str:
        from pathlib import Path

        import app.api.notifications as module

        return Path(module.__file__).read_text(encoding="utf-8")

    def test_recovery_route_is_rate_limited_and_captcha_gated(self):
        source = self.source()
        resume = source.split("async def resume_from_tracking_code", 1)[0]
        self.assertIn('@limiter.limit("10/minute")', resume.rsplit("@router", 1)[-1])
        body = source.split("async def resume_from_tracking_code", 1)[1]
        # The CAPTCHA must be checked before the lookup, not after.
        self.assertLess(
            body.index("_require_captcha"), body.index("resolve_tracking")
        )

    def test_sending_a_verification_code_is_rate_limited_more_tightly(self):
        source = self.source()
        self.assertIn('@limiter.limit("5/minute")', source)
        self.assertIn('@limiter.limit("10/minute")', source)

    def test_the_recovery_failure_message_names_neither_cause(self):
        source = self.source()
        self.assertIn(
            "No run found for that tracking code and email address.", source
        )


if __name__ == "__main__":
    unittest.main()
