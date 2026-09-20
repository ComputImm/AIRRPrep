# Test image for the component-matrix cases that cannot run on Windows
# (Supplementary Table S2): the three ClusterSets operations and the two
# reference-guided assembly operations.
#
# Those cases fail on Windows before any comparison can be made, on both sides
# and for the same reason: pRESTO creates the file it hands to the external
# tool with tempfile.NamedTemporaryFile and passes it while it is still open,
# which Windows will not let a second process open -- vsearch reports "Unable
# to open uc file for writing", and makeblastdb writes no database at all, so
# every pair fails to assemble. This image runs the same harness on Linux,
# where the two implementations are comparable.
#
# It is not the deployment image: it installs only what the matrix imports, at
# the versions in presto-backend/requirements.txt, and runs AIRRPrep's own code
# from the mounted repository. The external tools are the official releases,
# pinned by checksum -- vsearch 2.31.0, the same release as the vsearch.exe
# used for the Windows cases, and BLAST+ 2.17.0, the same as the host's.
#
#   paper/test/cluster-test/fetch_tools.sh
#   docker build -t airrprep-cluster-test paper/test/cluster-test
#   run_container_cases.sh does both, then runs the cases

FROM python:3.12-slim

# The tools come from .cache/, filled by fetch_tools.sh from the official
# releases and verified there by checksum -- not downloaded during the build,
# because BuildKit cannot resume an interrupted fetch and the BLAST+ release is
# ~300 MB over a slow link.
COPY .cache/vsearch /opt/tools/vsearch
COPY .cache/blastn /opt/tools/blastn
COPY .cache/makeblastdb /opt/tools/makeblastdb
# blastn is the only one of the three that is not self-contained: it links
# against libgomp (OpenMP), which the slim image does not carry.
RUN chmod +x /opt/tools/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# pRESTO and the packages app.pipeline.executor reaches through its wrappers,
# at the versions in requirements.txt. --no-deps keeps the transitive set
# explicit so the image cannot silently drift from the deployed one.
RUN pip install --no-cache-dir --no-deps \
        presto==0.7.9 \
        biopython==1.87 \
        numpy==2.4.4 \
        scipy==1.17.1 \
        pandas==3.0.3 \
        python-dateutil==2.9.0.post0 \
        pytz==2025.2 \
        tzdata==2025.2 \
        six==1.17.0 \
        packaging==25.0 \
        redis==7.4.0 \
        fastapi==0.136.1 \
        starlette==1.0.0 \
        pydantic==2.13.4 \
        pydantic_core==2.46.4 \
        annotated-doc==0.0.4 \
        annotated-types==0.7.0 \
        typing_extensions==4.15.0 \
        typing-inspection==0.4.2 \
        anyio==4.13.0 \
        sniffio==1.3.1 \
        idna==3.14 \
    && python -c "import presto.Sequence, presto.Applications, Bio.SeqIO, redis, fastapi" \
    && /opt/tools/vsearch --version \
    && /opt/tools/blastn -version

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MATRIX_PYTHON=python \
    MATRIX_SCRIPTS=/usr/local/bin \
    VSEARCH_BIN=/opt/tools/vsearch \
    PATH=/opt/tools:$PATH \
    WORKER_CPUS=4

WORKDIR /work
