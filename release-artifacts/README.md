# Release artifacts

These archives are the bulky evidence behind the manuscript: the
component matrix's fixtures and per-case outputs, the single-cell and
TRUST4 validation outputs, and the command-line benchmark's run
directories. They are too large to commit sensibly, so they are not in
this repository: they are archived on Zenodo at

    https://doi.org/10.5281/zenodo.22858375

which is registered as a supplement to the software record
(10.5281/zenodo.22857985). `SHA256SUMS` stays here, beside the
code, so a download can be checked against a checksum that was
not distributed with it.

`../paper/EXPECTED_OUTPUTS.sha256` lists the checksum of every file
inside them, so a re-run can be checked file by file without
downloading the archives at all.

`airrprep-backend-image.tar.gz`, when present, is `docker save` of the
backend image built from `backend/Dockerfile`; load it with
`docker load < airrprep-backend-image.tar.gz`.
