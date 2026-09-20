# Container image

The backend image is built from `backend/Dockerfile`. It is a three-stage
build on `python:3.12-slim`:

1. **builder** — compiles the Python dependencies into `/opt/venv`, so no
   compiler reaches the runtime image;
2. **trust4-builder** — downloads and compiles TRUST4 at the pinned release
   and flattens its reference FASTAs into `/opt/trust4/references`;
3. **runtime** — installs BLAST+, samtools, MUSCLE 3, VSEARCH, CD-HIT, perl and
   zlib from Debian packages, copies the venv and TRUST4 in, and runs as an
   unprivileged user (`appuser`, uid 1000) on port 8743.

## Build

```bash
cd backend
docker build -t airrprep-backend:local \
  --build-arg AIRRPREP_VERSION="$(git describe --tags --always --dirty)" .
```

`AIRRPREP_VERSION` is written into every `provenance.json` a run produces, so
a result always records the build it came from. `TRUST4_VERSION` (default
`1.1.9`) pins the TRUST4 release.

## Run

```bash
cd backend
cp .env.example .env     # then fill in the values SECURITY.md marks as required
docker compose up --build
```

`docker-compose.yml` starts Redis and the backend; the entrypoint caps the
container at `CPU_FRACTION` of the host's cores.

## Which tool versions an image contains

The Debian packages are deliberately **not** version-pinned in the Dockerfile,
because pinning them to one Debian point release makes the image stop building
as soon as that release moves. Instead the build records the version it
resolved for each of them inside the image:

```bash
docker run --rm airrprep-backend:local cat /app/TOOL_VERSIONS.txt
```

which prints something like

```
# Tool versions resolved when this image was built
# base image: python:3.12-slim
build_date=2026-09-19T17:41:02Z
debian=13.2
python=3.12.14
samtools=1.21-1
ncbi-blast+=2.16.0+ds-2
muscle3=3.8.1551-8
vsearch=2.29.1-1
cd-hit=4.8.1-6
perl=5.40.1-2
zlib1g=1:1.3.dfsg+really1.3.1-1
libpq5=17.2-1
trust4=1.1.9
usearch=not included (proprietary; set USEARCH_BIN to your own binary)
```

Record that output beside a deployment, or publish it with the release, so the
exact contents of an image can be checked afterwards. `make-tool-versions.sh`
in this directory builds the image and writes the manifest to
`tool-versions.md`:

```bash
docker/make-tool-versions.sh            # or: docker/make-tool-versions.sh <tag>
```

Run it once per release and commit the result, so the versions an image
contains are on record even after the image itself is gone.

## Identifying an image

Once an image is pushed to a registry it also carries an immutable digest:

```bash
docker image inspect --format '{{index .RepoDigests 0}}' airrprep-backend:local
```

Reference a deployment by that digest rather than by a tag, and set
`AIRRPREP_IMAGE` to it so it is recorded in every run's `provenance.json`.

## USEARCH

USEARCH is proprietary and is **not** in the image. Nothing defaults to it:
clustering defaults to VSEARCH and reference-guided assembly to BLAST+, both of
which the image carries, and no predefined workflow selects it. A deployment
that holds a USEARCH licence mounts its own binary:

```bash
docker run -v /opt/usearch:/opt/usearch:ro \
           -e USEARCH_BIN=/opt/usearch/usearch \
           airrprep-backend:local
```

Selecting USEARCH without one fails with a message naming the licence
requirement and the open alternatives, not with "executable not found".
`backend/tests/test_no_proprietary_binaries.py` asserts that the tree, the
build files and the requirements contain no USEARCH binary and that no default
selects it.
