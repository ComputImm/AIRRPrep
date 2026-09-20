#!/usr/bin/env bash
# Put the external tools the test image needs into .cache/, from their official
# releases and verified by checksum: vsearch (clustering) and the two BLAST+
# programs pRESTO calls for reference-guided assembly.
#
# The Dockerfile copies .cache/ instead of downloading during the build, because
# BuildKit cannot resume an interrupted ADD and the BLAST+ release is ~300 MB.
# Already-present files are left alone, so a rebuild costs nothing.
set -euo pipefail

# Git Bash keeps the execute bit off on this filesystem, so presence is tested
# with -f, and path translation must stay on here: the caller turns it off for
# docker, but curl on Windows needs a Windows path.
unset MSYS_NO_PATHCONV

HERE="$(cd "$(dirname "$0")" && pwd)"
CACHE="$HERE/.cache"
VSEARCH_URL=https://github.com/torognes/vsearch/releases/download/v2.31.0/vsearch-2.31.0-linux-x86_64.tar.gz
VSEARCH_SHA=1f07aec19cdeaf2a0ce8d9e3c9e6bb76a5cbf54e86d40bc50cb314a06ace2a16
BLAST_URL=https://ftp.ncbi.nlm.nih.gov/blast/executables/blast+/2.17.0/ncbi-blast-2.17.0+-x64-linux.tar.gz
BLAST_SHA=3888112d8207831aa47371d93583c601f058f88b5db22dc782438b039a3a411b

mkdir -p "$CACHE"

# curl -C - resumes a partial download, which this connection needs.
fetch() {
  local url=$1 out=$2 sha=$3
  [ -f "$out" ] && echo "$sha *$out" | sha256sum -c --quiet - 2>/dev/null && return 0
  echo "downloading $(basename "$out") ..."
  curl -fL -C - -o "$out" "$url"
  echo "$sha *$out" | sha256sum -c --quiet -
}

if [ ! -f "$CACHE/vsearch" ]; then
  fetch "$VSEARCH_URL" "$CACHE/vsearch.tar.gz" "$VSEARCH_SHA"
  tar -xzf "$CACHE/vsearch.tar.gz" -C "$CACHE" --strip-components=2 \
      vsearch-2.31.0-linux-x86_64/bin/vsearch
  rm -f "$CACHE/vsearch.tar.gz"
fi

if [ ! -f "$CACHE/blastn" ] || [ ! -f "$CACHE/makeblastdb" ]; then
  fetch "$BLAST_URL" "$CACHE/blast.tar.gz" "$BLAST_SHA"
  # Only the two programs pRESTO calls; the full release is 1.5 GB unpacked.
  tar -xzf "$CACHE/blast.tar.gz" -C "$CACHE" --strip-components=2 \
      "ncbi-blast-2.17.0+/bin/blastn" "ncbi-blast-2.17.0+/bin/makeblastdb"
  rm -f "$CACHE/blast.tar.gz"
fi

chmod +x "$CACHE"/vsearch "$CACHE"/blastn "$CACHE"/makeblastdb
ls -l "$CACHE"
