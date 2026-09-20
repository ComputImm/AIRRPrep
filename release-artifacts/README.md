# Release artifacts

These archives are the bulky evidence behind the manuscript: the
component matrix's fixtures and per-case outputs, the single-cell and
TRUST4 validation outputs, and the command-line benchmark's run
directories. They are too large to commit sensibly, so attach them to
the tagged release instead and keep `SHA256SUMS` beside them.

`../paper/EXPECTED_OUTPUTS.sha256` lists the checksum of every file
inside them, so a re-run can be checked file by file without
downloading the archives at all.

`airrprep-backend-image.tar.gz`, when present, is `docker save` of the
backend image built from `backend/Dockerfile`; load it with
`docker load < airrprep-backend-image.tar.gz`.
