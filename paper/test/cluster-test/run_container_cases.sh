#!/usr/bin/env bash
# Build the Linux test image and run, inside it, the five component-matrix cases
# that cannot run on Windows, merging them into component_matrix.json:
# ClusterSets all/barcode/set with vsearch, and reference-guided assembly
# (AssemblePairs reference and sequential). See Dockerfile for why.
#
# Run from anywhere (Git Bash on Windows, or any POSIX shell). The fixtures must
# already exist (work/fixtures, built by a host run of run_component_matrix.py);
# --reuse picks them up through the repo-relative paths in _fixtures.json.
set -euo pipefail

# pwd -W gives a Windows path (C:/...) under Git Bash, which Docker Desktop needs.
REPO="$(cd "$(dirname "$0")/../../.." && { pwd -W 2>/dev/null || pwd; })"
DOCKER="${DOCKER:-docker}"

bash "$(dirname "$0")/fetch_tools.sh"

export MSYS_NO_PATHCONV=1   # keep Git Bash from rewriting the container paths
"$DOCKER" build -t airrprep-cluster-test "$REPO/paper/test/cluster-test"

# The repository is mounted whole: the harness reads the fixtures and the bench
# inputs from it and writes work/cases and component_matrix.json back into it.
# Building the case list registers this run's companion files in the upload
# store, which is Redis, so the container uses the one already running on the
# host. The USEARCH cases are not run here: USEARCH v7 has no redistributable
# Linux build, and the deployment image ships without it.
"$DOCKER" run --rm \
  -e REDIS_URL="redis://host.docker.internal:6379/0" \
  --add-host host.docker.internal:host-gateway \
  -v "$REPO:/repo" \
  -w /repo/paper/test/component_matrix \
  airrprep-cluster-test \
  python run_component_matrix.py --reuse --merge \
    "ClusterSets.all [vsearch]" "ClusterSets.barcode [vsearch]" "ClusterSets.set [vsearch]" \
    AssemblePairs.reference AssemblePairs.sequential
