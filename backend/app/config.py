from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent

JOBS_DIR = BASE_DIR / "jobs"

# Where session uploads live. Anchored to the project root rather than the
# process's working directory: the API and the Celery worker are started
# separately, and if they disagreed about where "uploads" is, the retention
# sweep would quietly scan an empty directory while files piled up elsewhere.
UPLOADS_DIR = BASE_DIR / "uploads"


# app/config.py
import os
import redis

from app.core.cpu import budgeted_cpus

# Redis configuration (set REDIS_URL, e.g. redis://:password@redis:6379/0 in docker-compose)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# --- Retention -------------------------------------------------------------
# How long an upload is kept before it is deleted from disk and from Redis.
# This is the promise made to the user ("your files are removed after N days"),
# so the session record and its file records expire together -- a session that
# outlived its uploads would list files that can no longer be read.
UPLOAD_RETENTION_DAYS = int(os.getenv("UPLOAD_RETENTION_DAYS", "10"))
UPLOAD_RETENTION_SECONDS = UPLOAD_RETENTION_DAYS * 86400

# TTL settings
SESSION_TTL = UPLOAD_RETENTION_SECONDS
JOB_TTL = 86400  # 1 day
FILE_TTL = UPLOAD_RETENTION_SECONDS

# Per-session ceiling on stored uploads. Without it a single session can fill
# the disk one allowed-size file at a time, since each upload is only checked
# against the per-file cap.
MAX_SESSION_UPLOAD_MB = int(os.getenv("MAX_SESSION_UPLOAD_MB", "2048"))
MAX_SESSION_UPLOAD_BYTES = MAX_SESSION_UPLOAD_MB * 1024 * 1024

# Pipelines a user saved to re-run later (app/core/pipeline_store.py). Kept as
# long as uploads are: a saved pipeline is only useful while the session that
# owns it still exists.
SAVED_PIPELINE_TTL = UPLOAD_RETENTION_SECONDS
MAX_SAVED_PIPELINES = int(os.getenv("MAX_SAVED_PIPELINES", "50"))

# A job the user is being emailed about outlives the normal 1-day job TTL:
# they are told to come back later with a tracking code, and that code is
# worthless if the job document has already expired. Applied by job_store to
# any job that carries a tracking_code, and to the tracking record itself.
TRACKED_JOB_TTL = int(os.getenv("TRACKED_JOB_TTL_DAYS", "7")) * 86400

# CORS — comma separated list of allowed frontend origins, e.g.
#   ALLOWED_ORIGINS=http://localhost:8080,https://app.example.com
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:8080"
    ).split(",")
    if origin.strip()
    
]

# --- Bulk: external pRESTO helper binaries --------------------------------
# AlignSets (muscle) and ClusterSets (usearch / vsearch / cd-hit-est) shell out
# to these. They are operator settings, never step parameters: pRESTO's own
# --exec flag is a local-CLI convenience, but on a hosted service letting a
# request name the executable would let it pick which binary the worker runs.

# How many CPUs a step may use when it drives an external tool. Some of those
# tools take a thread count directly (usearch, cd-hit-est); the aligners pRESTO
# invokes per record -- blastn and ublast, both hard-coded to one thread each,
# and muscle, which has no thread option at all -- can only use the machine by
# running several of those processes at once, so this is also the pool size for
# those steps. Sized off app/core/cpu.py, i.e. WORKER_CPUS / CPU_FRACTION, and
# the whole machine when neither is configured.
EXTERNAL_TOOL_CPUS = budgeted_cpus()

MUSCLE_BIN = os.getenv("MUSCLE_BIN", "muscle")
CLUSTER_BINS = {
    "usearch": os.getenv("USEARCH_BIN", "usearch"),
    "vsearch": os.getenv("VSEARCH_BIN", "vsearch"),
    "cd-hit-est": os.getenv("CDHIT_BIN", "cd-hit-est"),
}

# Reference-guided assembly drives one of these once per read pair.
ALIGNER_BINS = {
    "blastn": os.getenv("BLASTN_BIN", "blastn"),
    "usearch": os.getenv("USEARCH_BIN", "usearch"),
}
ALIGNER_DB_BINS = {
    "blastn": os.getenv("MAKEBLASTDB_BIN", "makeblastdb"),
    "usearch": os.getenv("USEARCH_BIN", "usearch"),
}

# USEARCH is proprietary and is not redistributed with AIRRPrep or its
# container image, so neither default may be a USEARCH one: pRESTO's own
# defaults (`usearch` for both ClusterSets and reference-guided assembly)
# would make an operation that cannot run on a stock deployment the one a
# user gets without choosing. Both defaults below are tools the image
# carries. A deployment that holds a USEARCH licence can still select it,
# after pointing USEARCH_BIN at its own binary.
DEFAULT_CLUSTER_TOOL = os.getenv("DEFAULT_CLUSTER_TOOL", "vsearch")
DEFAULT_REFERENCE_ALIGNER = os.getenv("DEFAULT_REFERENCE_ALIGNER", "blastn")

# --- Single-cell: TRUST4 (raw FASTQ/BAM assembly) -------------------------
# TRUST4 is built into the runtime image (see Dockerfile) and its reference
# bundle is shipped alongside it. Every value below is overridable so the same
# image can point at a mounted reference volume instead.
#
# TRUST4_BIN is the `run-trust4` driver script (not the `trust4` executable):
# only the driver knows how to chain extractor -> assembler -> annotator and
# emit the *_barcode_report.tsv that Trust4Adapter parses.
TRUST4_BIN = os.getenv("TRUST4_BIN", "run-trust4")
# Used only by the BAM "extract reads first" path, which converts a BAM that
# TRUST4's own bam-extractor cannot read into FASTQ. See trust4_runner.py.
SAMTOOLS_BIN = os.getenv("SAMTOOLS_BIN", "samtools")
TRUST4_REF_DIR = os.getenv("TRUST4_REF_DIR", "/opt/trust4/references")
# Unset (or blank) means "size it off the machine": two thirds of the cores
# available to this container. See app/core/cpu.py.
_trust4_threads_env = os.getenv("TRUST4_THREADS", "").strip()
TRUST4_THREADS = int(_trust4_threads_env) if _trust4_threads_env else budgeted_cpus()
# Hard cap on one assembly so a pathological input can't pin a Celery worker
# forever. 0 disables the timeout.
TRUST4_TIMEOUT = int(os.getenv("TRUST4_TIMEOUT", str(6 * 3600)))
# Optional 10x barcode whitelist (e.g. 737K-august-2016.txt). Not shipped in
# the image — 10x does not permit redistribution — so it stays unset unless
# mounted and pointed at explicitly.
TRUST4_BARCODE_WHITELIST = os.getenv("TRUST4_BARCODE_WHITELIST") or None


def _ref(env_name: str, filename: str) -> str:
    return os.getenv(env_name) or str(Path(TRUST4_REF_DIR) / filename)


# species -> the two reference FASTAs TRUST4 needs: the coordinate/sequence
# V/D/J/C file (-f) and the detailed IMGT annotation file (--ref).
TRUST4_SPECIES_REFS: dict[str, dict[str, str]] = {
    "human": {
        "label": "Human (GRCh38)",
        # TRUST4_REF_FASTA / TRUST4_VDJ_REF_FASTA are the pre-existing
        # single-species env names; they keep working as human overrides.
        "vdj_ref": _ref("TRUST4_VDJ_REF_FASTA", "hg38_bcrtcr.fa"),
        "ref": _ref("TRUST4_REF_FASTA", "human_IMGT+C.fa"),
    },
    "mouse": {
        "label": "Mouse (GRCm38)",
        "vdj_ref": _ref("TRUST4_MOUSE_VDJ_REF_FASTA", "GRCm38_bcrtcr.fa"),
        "ref": _ref("TRUST4_MOUSE_REF_FASTA", "mouse_IMGT+C.fa"),
    },
}

TRUST4_DEFAULT_SPECIES = os.getenv("TRUST4_DEFAULT_SPECIES", "human")


# --- Email notifications ---------------------------------------------------
# Long runs (big uploads, or pipelines containing slow components like
# BuildConsensus / AssemblePairs / TRUST4 assembly) ask the user for a
# verified email address before they may start, then mail them a tracking
# code on start and a link on completion. See app/core/estimate.py.
#
# With SMTP_HOST unset the mailer does not fail — it logs the message it
# would have sent, so the whole flow (including the verification code) is
# exercisable in local development without a mail server.
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
# "starttls" (default, port 587), "ssl" (port 465), or "none" (plaintext).
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
SMTP_TIMEOUT = int(os.getenv("SMTP_TIMEOUT", "15"))
MAIL_FROM = os.getenv("MAIL_FROM", "no-reply@localhost").strip()
MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "AIRR Preprocessor").strip()

# Base URL of the frontend, used to build the "view your results" links that
# go in the emails. No trailing slash.
PUBLIC_APP_URL = os.getenv("PUBLIC_APP_URL", "http://localhost:4287").rstrip("/")

# --- Notification thresholds ----------------------------------------------
# A run is considered "long" — and therefore gated behind email verification
# — when either the estimated runtime or the total input size crosses these.
NOTIFY_MIN_SECONDS = int(os.getenv("NOTIFY_MIN_SECONDS", "300"))  # 5 minutes
NOTIFY_MIN_INPUT_MB = float(os.getenv("NOTIFY_MIN_INPUT_MB", "150"))

# Verification codes: lifetime, how many wrong guesses are tolerated, and how
# long the user must wait before a new code can be sent to the same session.
EMAIL_CODE_TTL = int(os.getenv("EMAIL_CODE_TTL", "900"))  # 15 minutes
EMAIL_CODE_MAX_ATTEMPTS = int(os.getenv("EMAIL_CODE_MAX_ATTEMPTS", "5"))
EMAIL_CODE_RESEND_COOLDOWN = int(os.getenv("EMAIL_CODE_RESEND_COOLDOWN", "60"))

# Server-side key for the HMAC that turns an email address into the lookup
# value stored on a tracking record. A plain hash of an address can be
# reversed by hashing candidate addresses; a keyed one cannot without this
# secret, which lives in the environment and never in Redis. Set it (e.g.
# `python -c "import secrets; print(secrets.token_hex(32))"`) in every
# deployment and keep it stable: changing it invalidates outstanding tracking
# codes. Unset, app/core/email_verification.py falls back to a per-install
# key for local development and logs a warning.
EMAIL_HASH_SECRET = os.getenv("EMAIL_HASH_SECRET", "").strip()

# --- Anti-bot (CAPTCHA) ----------------------------------------------------
# Guards the two routes a script could abuse without a session of its own:
# sending verification emails (a mail-bomb vector) and tracking-code recovery
# (a guessing vector). See app/core/captcha.py.
#
# Set CAPTCHA_ENABLED=false to turn it off — useful for automated tests.
CAPTCHA_ENABLED = os.getenv("CAPTCHA_ENABLED", "true").strip().lower() not in (
    "false", "0", "no",
)
CAPTCHA_TTL = int(os.getenv("CAPTCHA_TTL", "300"))  # 5 minutes
CAPTCHA_LENGTH = int(os.getenv("CAPTCHA_LENGTH", "5"))
