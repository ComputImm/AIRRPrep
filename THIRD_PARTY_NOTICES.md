# Third-party notices

AIRRPrep is licensed under the GNU Affero General Public License v3.0 or later
(`LICENSE`). This file records what it redistributes or depends on, and under
what terms.

## Why AGPL-3.0

`backend/app/presto_tools/` contains **modified copies of pRESTO's tools**
(`AlignSets.py`, `AssemblePairs.py`, `BuildConsensus.py`, `ClusterSets.py`,
`CollapseSeq.py`, `ConvertHeaders.py`, `EstimateError.py`, `MaskPrimers.py`,
`PairSeq.py`, `ParseHeaders.py`, `SplitSeq.py`, `UnifyHeaders.py`), and
`backend/app/presto_wrappers/` calls pRESTO's library API directly. pRESTO is
distributed under the GNU Affero General Public License v3.0. A work that
redistributes modified AGPL code must itself be AGPL, and because AIRRPrep is
offered to users over a network, the AGPL's §13 network clause applies to the
hosted service as well as to the source.

The modifications to pRESTO's tools are described in the manuscript
(Supplementary Table S2) and are visible in the file headers. In summary:
`ClusterSets.py`'s external-tool invocation is constructed by AIRRPrep rather
than by pRESTO's helper, and `ConvertHeaders.py`'s MIGEC path streams the input
instead of indexing it.

## Bundled at build time (container image)

Installed by `backend/Dockerfile`; not included in this source tree. The
resolved version of each is recorded inside the image at
`/app/TOOL_VERSIONS.txt`.

| Component | Source | Licence |
| --- | --- | --- |
| TRUST4 1.1.9 | built from the upstream release tarball | MIT |
| BLAST+ (`ncbi-blast+`) | Debian package | Public domain (NCBI) / see package |
| samtools | Debian package | MIT |
| MUSCLE 3 (`muscle3`) | Debian package | Public domain |
| VSEARCH | Debian package | GPL-3.0 / BSD-2-Clause dual |
| CD-HIT (`cd-hit`) | Debian package | GPL-2.0 |
| Python 3.12 (`python:3.12-slim`) | Docker Official Image | PSF-2.0 |

## Not redistributed

| Component | Why |
| --- | --- |
| **USEARCH** | Proprietary. Its licence does not clearly permit redistribution in a public container. Not in the source tree, not in the image, not selected by any default, not required by any predefined workflow. A deployment holding its own licence points `USEARCH_BIN` at its binary. `backend/tests/test_no_proprietary_binaries.py` asserts all of this. |
| Public sequencing datasets | SRR4026043, ERR346600, SRR1383456 and the 10x Genomics Cell Ranger outputs are downloaded from their published sources; their checksums are in `paper/INPUT_DATASETS.sha256`. |

## Python dependencies (`backend/requirements.txt`)

| Package | Version | Licence |
| --- | --- | --- |
| presto | 0.7.9 | **AGPL-3.0** |
| biopython | 1.87 | Biopython License Agreement (BSD-like) |
| psycopg2-binary | 2.9.12 | LGPL-3.0 with exceptions |
| SQLAlchemy | 2.0.49 | MIT |
| aiofiles | 25.1.0 | Apache-2.0 |
| amqp | 5.3.1 | BSD-3-Clause |
| annotated-doc | 0.0.4 | MIT |
| annotated-types | 0.7.0 | MIT |
| anyio | 4.13.0 | MIT |
| billiard | 4.2.4 | BSD-3-Clause |
| celery | 5.6.3 | BSD-3-Clause |
| click | 8.3.3 | BSD-3-Clause |
| click-didyoumean | 0.3.1 | MIT |
| click-plugins | 1.1.1.2 | BSD-3-Clause |
| click-repl | 0.3.0 | MIT |
| colorama | 0.4.6 | BSD-3-Clause |
| fastapi | 0.136.1 | MIT |
| greenlet | 3.5.0 | MIT and PSF-2.0 |
| h11 | 0.16.0 | MIT |
| idna | 3.14 | BSD-3-Clause |
| kombu | 5.6.2 | BSD-3-Clause |
| limits | 3.13.0 | MIT |
| numpy | 2.4.4 | BSD-3-Clause and 0BSD and MIT and Zlib and CC0-1.0 |
| packaging | 24.2 | Apache-2.0 or BSD-2-Clause |
| pandas | 3.0.3 | BSD-3-Clause |
| prompt_toolkit | 3.0.52 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| pydantic_core | 2.46.4 | MIT |
| python-dateutil | 2.9.0.post0 | Apache-2.0 or BSD-3-Clause |
| python-multipart | 0.0.28 | Apache-2.0 |
| redis | 7.4.0 | MIT |
| scipy | 1.17.1 | BSD-3-Clause |
| six | 1.17.0 | MIT |
| slowapi | 0.1.9 | MIT |
| starlette | 1.0.0 | BSD-3-Clause |
| typing-inspection | 0.4.2 | MIT |
| typing_extensions | 4.15.0 | PSF-2.0 |
| tzdata | 2026.2 | Apache-2.0 |
| tzlocal | 5.3.1 | MIT |
| uvicorn | 0.46.0 | BSD-3-Clause |
| vine | 5.1.0 | BSD-3-Clause |
| wcwidth | 0.7.0 | MIT |

All of the above are AGPL-compatible: permissive licences can be combined into
an AGPL work, and LGPL-3.0 is compatible with AGPL-3.0.

## Frontend dependencies (`frontend/package.json`)

The web interface is built with React, TanStack Start and TanStack Router,
Radix UI primitives, Tailwind CSS, Recharts, `lucide-react`, `react-hook-form`,
`zod` and related packages. These are MIT-licensed, with a small number of
Apache-2.0 and ISC packages; `npm ls --all` or `bun pm ls` in `frontend/`
enumerates the exact set for a given lockfile, and each package's own licence
file is installed under `node_modules/`.

## Manuscript package

`paper/manuscript/oup-authoring-template.cls` is Oxford University Press's
authoring class, distributed under the LaTeX Project Public License v1.3 or
later, and is included so the manuscript compiles from an empty directory. It
is not part of AIRRPrep and is not covered by AIRRPrep's licence.
