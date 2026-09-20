# Security and privacy

AIRRPrep is a public service that accepts file uploads and runs long jobs
without requiring an account. This document states what it protects, what it
does not, and what an operator has to do. Every statement here is covered by
an automated test in `backend/tests/test_security_controls.py` unless it is
marked as an operator responsibility.

---

## What there is instead of accounts

Work is organised in a **browser session** with its own secret token. Every
session, file and job route is authorised against that token, and only a hash
of it is stored, so a dump of the data store does not hand out live sessions.

A session may verify an **email address**, which unlocks long-running jobs and
start/finish notifications. This is a reachability check, not an identity: it
proves a notification will arrive somewhere the user reads.

---

## Verification codes

A six-digit code is mailed to the address and entered back.

| Control | Setting | Default |
| --- | --- | --- |
| Code lifetime | `EMAIL_CODE_TTL` | 900 s (15 min) |
| Wrong guesses before the code is burned | `EMAIL_CODE_MAX_ATTEMPTS` | 5 |
| Resend cooldown | `EMAIL_CODE_RESEND_COOLDOWN` | 60 s |
| Rate limit on sending a code | route limit | 5 / minute / client address |

* The code is stored only as a SHA-256 salted with the session id — never in
  plain text.
* A wrong guess does **not** extend the code's expiry.
* After the attempt limit the record is deleted, so even the correct code stops
  working and a new one must be requested.
* Addresses are trimmed and lower-cased before storage and comparison, and
  malformed ones are refused before any mail is attempted.

## Tracking codes and recovery

A job started from an email-gated launch gets a six-digit tracking code,
emailed at start and at finish, which restores the run from any browser.

* Six digits is a million-wide space, which a script walks through in minutes,
  so **the code alone is not a credential**: recovery requires the code *and*
  the address it was issued to.
* The tracking record stores **HMAC-SHA256 of the normalised address**, keyed
  with `EMAIL_HASH_SECRET`, which lives in the deployment environment and not
  in the data store. A copy of the data store alone therefore does not allow
  addresses to be recovered by hashing candidates — which a bare SHA-256 would.
* A wrong code and a wrong address produce the **same** answer, so the route is
  not an oracle for which codes exist.
* The recovery route requires a solved CAPTCHA *before* the lookup, and is
  limited to 10 requests per minute per client address.
* The link in an email pre-fills the **code only**; no recovery URL ever
  contains the user's address.
* Tracking records expire `TRACKED_JOB_TTL_DAYS` (default 7) days after their
  last use.

## CAPTCHA

Self-hosted, no third-party call. The answer is stored hashed and the
challenge is **destroyed on first use**, right or wrong, so a single image
cannot be guessed at repeatedly. It is a speed bump against scripted access,
not a wall; it is image-only, so it is not usable with a screen reader, and
both routes it guards have an alternative path that does not go through it.

---

## Data retention and deletion

| Data | Where | Retention |
| --- | --- | --- |
| Uploaded files | job workspace on disk | `UPLOAD_RETENTION_DAYS`, default 10 days |
| Job outputs | job workspace on disk | with the job; a tracked job stays reachable for `TRACKED_JOB_TTL_DAYS`, default 7 days, after its last use |
| Session record (incl. the verified address, in plain text) | Redis | with the session |
| Job record (incl. the address the notifications go to, in plain text) | Redis | with the job |
| Pending verification code | Redis, hashed | 15 minutes |
| Tracking record (address as a keyed HMAC) | Redis | 7 days from last use |
| Server logs | operator's logging stack | operator's policy |

**The verified address is held in plain text** on the session record and on the
records of jobs started from that session, because it is needed to deliver the
notifications. Those records expire with the session and job retention
windows. The tracking record, which is the one a public route looks up, holds
only the keyed HMAC.

Deleting a session's files deletes the uploads and outputs; there is no
separate "delete my address" route, so an operator asked to erase a user's
data removes the session and job records.

---

## Operator responsibilities

These are **not** enforced by the code and must be done by whoever deploys it.

1. **Set `EMAIL_HASH_SECRET`.** Without it the service generates a development
   key and stores it in Redis, beside the hashes it protects — which defeats
   the point. The service logs a warning when this happens.
2. **Set `REDIS_PASSWORD`** and keep both it and `EMAIL_HASH_SECRET` out of
   the image, the repository and the data store; supply them through the
   environment or a secret manager. Session tokens are generated per session
   with `secrets.token_urlsafe(32)` and stored only as a SHA-256, so there is
   no signing key to rotate for them.
3. **Configure SMTP** (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
   `MAIL_FROM`) over TLS. Mail is sent by the backend directly; the addresses
   and the mail server are the operator's to protect.
4. **Terminate TLS in front of the service.** The application speaks plain
   HTTP behind a reverse proxy and trusts `X-Forwarded-*`; expose it only
   through a proxy you control, or the per-client rate limits key on the wrong
   address.
5. **Set `ALLOWED_ORIGINS`** to the origins that should be able to call the
   API.
6. **Review the limits** (`UPLOAD_RETENTION_DAYS`, `TRACKED_JOB_TTL_DAYS`,
   `MAX_UPLOAD_SIZE_MB`, `MAX_SESSION_UPLOAD_MB`, the route rate limits)
   against your own policy; the defaults suit a small public instance.
7. **Do not run the container as root** or mount the host filesystem into it.
   The image already runs as an unprivileged user.
8. **Decide your own privacy notice.** AIRRPrep stores whatever a user
   uploads; on a public instance, say so.

---

## Reporting a vulnerability

Email <preprocessing@computimm.com> with a description and, if possible, a
reproduction. Please do not open a public issue for a security problem.
