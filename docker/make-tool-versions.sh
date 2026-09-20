#!/usr/bin/env bash
# Build the backend image and write docker/tool-versions.md: the version of
# every tool the image actually resolved at build time.
#
# The Debian packages in backend/Dockerfile are not version-pinned, because
# pinning them to one Debian point release makes the image stop building as
# soon as that release moves. The build therefore records what it resolved
# inside the image, and this script copies that record out so it survives the
# image.
#
#     docker/make-tool-versions.sh [tag]
#
# Run it once per release and commit the result.

set -euo pipefail

TAG="${1:-airrprep-backend:local}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$HERE/../backend"
OUT="$HERE/tool-versions.md"

if ! docker info >/dev/null 2>&1; then
  echo "The Docker engine is not reachable. Start Docker and try again." >&2
  exit 1
fi

VERSION="$(git -C "$HERE/.." describe --tags --always --dirty 2>/dev/null || echo dev)"

echo "Building $TAG (AIRRPREP_VERSION=$VERSION) ..."
docker build -t "$TAG" --build-arg "AIRRPREP_VERSION=$VERSION" "$BACKEND"

{
  echo "# Tool versions in the AIRRPrep backend image"
  echo
  echo "Image tag: \`$TAG\`"
  echo "AIRRPrep version: \`$VERSION\`"
  echo "Local image id: \`$(docker image inspect --format '{{.Id}}' "$TAG")\`"
  echo "Size: $(docker image inspect --format '{{.Size}}' "$TAG") bytes"
  digest="$(docker image inspect --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' "$TAG")"
  if [ -n "$digest" ]; then
    echo "Registry digest: \`$digest\`"
  else
    echo "Registry digest: not pushed yet; push the image and rerun to record it."
  fi
  echo
  echo 'Read the same manifest back out of any image with'
  echo
  echo '```bash'
  echo "docker run --rm $TAG cat /app/TOOL_VERSIONS.txt"
  echo '```'
  echo
  echo '```'
  docker run --rm "$TAG" cat /app/TOOL_VERSIONS.txt
  echo '```'
} > "$OUT"

echo "wrote $OUT"
