# Test image for the TRUST4 single-cell routes (Supplementary Table S7).
#
# Not the deployment image. It exists because the deployment image
# (presto-backend/Dockerfile) compiles TRUST4 and installs the full backend,
# ~700 MB of downloads, which could not be fetched on a slow connection. This
# image uses the same TRUST4 release (1.1.9, bioconda build) and TRUST4's own
# v1.1.9 human references, and runs AIRRPrep's unmodified single-cell code
# (Trust4Runner and the adapters), mounted read-only at run time.
#
#   docker build -t airrprep-trust4-test paper/test/trust4-test
#   see run_trust4_tests.sh for the run command

FROM quay.io/biocontainers/trust4:1.1.9--h7f5d12c_0 AS trust4
FROM quay.io/biocontainers/samtools:1.23.1--ha83d96e_0 AS samtools

FROM python:3.12-slim

# Each conda environment keeps its own lib/ beside bin/, where the binaries'
# $ORIGIN-relative rpath expects it.
COPY --from=trust4 /usr/local /opt/trust4env
COPY --from=samtools /usr/local /opt/samtoolsenv

# Only what app.singlecell imports, at the versions in requirements.txt
# (Bio.SeqIO imports Bio.Align, which needs numpy).
RUN pip install --no-cache-dir --no-deps \
        numpy==2.4.4 \
        redis==7.4.0 \
        pydantic==2.13.4 \
        pydantic_core==2.46.4 \
        annotated-types==0.7.0 \
        typing_extensions==4.15.0 \
        typing-inspection==0.4.2 \
        biopython==1.87

COPY refs/ /opt/trust4/references/

ENV PATH="/opt/trust4env/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRUST4_BIN=/opt/trust4env/bin/run-trust4 \
    TRUST4_REF_DIR=/opt/trust4/references \
    TRUST4_VERSION=1.1.9 \
    SAMTOOLS_BIN=/opt/samtoolsenv/bin/samtools

WORKDIR /work
