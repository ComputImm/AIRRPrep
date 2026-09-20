# syntax=docker/dockerfile:1

########################
# Builder: compile deps into a venv, keep build tools out of the final image
########################
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

########################
# TRUST4: compiled from source, used by the single-cell raw-read adapters
# (app/singlecell/trust4_runner.py) to assemble V(D)J contigs from 10x
# FASTQ/BAM input. Built in its own stage so g++/make never reach runtime.
########################
FROM python:3.12-slim AS trust4-builder

ARG TRUST4_VERSION=1.1.9

# libncurses-dev is for the samtools-0.1.19 tree TRUST4 bundles: building
# bam-extractor triggers a full `make` in there, and that tree's own samtools
# binary needs curses even though bam-extractor itself only links libbam.a.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        libncurses-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src

RUN curl -fsSL \
        "https://github.com/liulab-dfci/TRUST4/archive/refs/tags/v${TRUST4_VERSION}.tar.gz" \
        -o trust4.tar.gz \
    && tar -xzf trust4.tar.gz \
    && mv "TRUST4-${TRUST4_VERSION}" /opt/trust4 \
    && rm trust4.tar.gz \
    && make -C /opt/trust4

# The reference FASTAs ship inside the TRUST4 source tree — human at the root,
# mouse under mouse/. Flatten the ones app/config.py::TRUST4_SPECIES_REFS
# names into one directory so a deployment can swap TRUST4_REF_DIR for a
# mounted volume without touching anything else.
#
# Collected by pattern rather than by exact path so a TRUST4 release that
# moves or renames a reference doesn't break the build; whatever ends up
# missing is reported at runtime, per species, by /api/singlecell/trust4/status.
RUN mkdir -p /opt/trust4/references \
    && find /opt/trust4 -maxdepth 2 \
         \( -name '*bcrtcr.fa' -o -name '*IMGT+C.fa' \) \
         -exec cp -t /opt/trust4/references/ {} + \
    && ls -l /opt/trust4/references/

########################
# Runtime: minimal, non-root
########################
FROM python:3.12-slim AS runtime

ARG TRUST4_VERSION=1.1.9
# Release tag of this AIRRPrep build, recorded in every provenance file.
ARG AIRRPREP_VERSION=dev

# perl runs the run-trust4 driver script; zlib1g is what the TRUST4 binaries
# link against for gzipped FASTQ/BAM input.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        perl \
        zlib1g \
        samtools \
        ncbi-blast+ \
        muscle3 \
        vsearch \
        cd-hit \
    && rm -rf /var/lib/apt/lists/*

# USEARCH is proprietary and is deliberately NOT part of this image: its
# licence does not clearly permit redistribution in a public container. No
# predefined workflow needs it (VSEARCH and CD-HIT cover ClusterSets). A
# deployment that holds its own USEARCH licence can mount the binary and point
# USEARCH_BIN at it, e.g. `-v /opt/usearch:/opt/usearch:ro
# -e USEARCH_BIN=/opt/usearch/usearch`.
RUN ln -s /usr/bin/muscle3 /usr/local/bin/muscle

# Record the resolved version of every tool this image installs. The Debian
# packages above are not version-pinned, so without this the only way to know
# what an image actually contains would be its registry digest. Writing the
# manifest into the image means the versions can be read back from the image
# itself:  docker run --rm <image> cat /app/TOOL_VERSIONS.txt
RUN mkdir -p /app \
    && { \
        echo "# Tool versions resolved when this image was built"; \
        echo "# base image: python:3.12-slim"; \
        echo "build_date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; \
        echo "debian=$(cat /etc/debian_version)"; \
        echo "python=$(python --version 2>&1 | cut -d' ' -f2)"; \
        for pkg in samtools ncbi-blast+ muscle3 vsearch cd-hit perl zlib1g libpq5; do \
            printf '%s=%s\n' "$pkg" \
                "$(dpkg-query -W -f='${Version}' "$pkg" 2>/dev/null || echo absent)"; \
        done; \
        echo "trust4=${TRUST4_VERSION}"; \
        echo "usearch=not included (proprietary; set USEARCH_BIN to your own binary)"; \
    } > /app/TOOL_VERSIONS.txt

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --shell /bin/false --create-home appuser

COPY --from=builder /opt/venv /opt/venv
COPY --from=trust4-builder /opt/trust4 /opt/trust4

# run-trust4 resolves its sibling binaries from its own real path, so a
# symlink onto PATH is enough — no need to put /opt/trust4 on PATH itself.
RUN ln -s /opt/trust4/run-trust4 /usr/local/bin/run-trust4

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRUST4_BIN=/opt/trust4/run-trust4 \
    TRUST4_REF_DIR=/opt/trust4/references \
    TRUST4_VERSION=${TRUST4_VERSION} \
    AIRRPREP_VERSION=${AIRRPREP_VERSION}

WORKDIR /app

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/jobs /app/uploads && chown -R appuser:appuser /app \
    && install -m 0755 /app/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

USER appuser

EXPOSE 8743

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8743/ || exit 1

# Caps this container at two thirds of the host's cores — see the script.
ENTRYPOINT ["docker-entrypoint.sh"]

#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8743"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8743", "--proxy-headers", "--forwarded-allow-ips", "*"]

