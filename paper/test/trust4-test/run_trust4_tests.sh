#!/usr/bin/env bash
# Build the TRUST4 test image and run paper/test/validate_trust4.py in it.
# Run from the repository root (Git Bash on Windows, or any POSIX shell).
set -euo pipefail

# pwd -W gives a Windows path (C:/...) under Git Bash, which Docker Desktop needs.
REPO="$(cd "$(dirname "$0")/../../.." && { pwd -W 2>/dev/null || pwd; })"
export MSYS_NO_PATHCONV=1   # keep Git Bash from rewriting the container paths

docker build -t airrprep-trust4-test "$REPO/paper/test/trust4-test"

docker run --rm \
  -e TRUST4_THREADS="${TRUST4_THREADS:-}" \
  -v "$REPO/presto-backend/app:/app/app:ro" \
  -v "$REPO/test-data:/data/test-data:ro" \
  -v "$REPO/paper/test:/data/out" \
  airrprep-trust4-test \
  python /data/out/validate_trust4.py
