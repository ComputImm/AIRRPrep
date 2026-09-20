# AIRRPrep

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.22857984.svg)](https://doi.org/10.5281/zenodo.22857984)
[![Release](https://img.shields.io/github/v/tag/ComputImm/AIRRPrep?label=release&sort=semver)](https://github.com/ComputImm/AIRRPrep/releases/tag/v1.0.0)
[![Licence: AGPL v3.0-or-later](https://img.shields.io/badge/licence-AGPL--3.0--or--later-blue.svg)](LICENSE)

Validated workflows for bulk and single-cell AIRR-seq preprocessing.

AIRRPrep exposes [pRESTO](https://presto.readthedocs.io) and
[TRUST4](https://github.com/liulab-dfci/TRUST4) through a web application. It
separates bulk and single-cell data, checks every workflow against the files
actually uploaded *before* it runs, and makes each run inspectable and
repeatable. A hosted instance runs at <https://preprocessing.computimm.com>;
no account is required.

This repository is the source of the manuscript *AIRRPrep: validated workflows
for bulk and single-cell AIRR-seq preprocessing*, together with every script,
input description, report and checksum behind the numbers it reports.

---

## Release and citation

The version the manuscript describes is tag
[`v1.0.0`](https://github.com/ComputImm/AIRRPrep/releases/tag/v1.0.0), commit
`9148dba8bdd4c516b80db4eece07dd0a0b23a929`, archived on Zenodo:

| | |
| --- | --- |
| This version (`v1.0.0`) | [10.5281/zenodo.22857985](https://doi.org/10.5281/zenodo.22857985) |
| All versions (resolves to the newest) | [10.5281/zenodo.22857984](https://doi.org/10.5281/zenodo.22857984) |

Cite the **version** DOI to point at the exact code a result came from, and the
**all-versions** DOI to refer to the software in general. `CITATION.cff` carries
the same metadata, so GitHub's *Cite this repository* button and tools that read
it stay in step with this file.

```bibtex
@software{airrprep_v1_0_0,
  author    = {Esmaeili, Parsa and Chaker Hosseini Zavareh, Fatemeh and
               Abdolahi, Nika and Eslahchi, Changiz},
  title     = {{AIRRPrep}: validated workflows for bulk and single-cell
               {AIRR}-seq preprocessing},
  version   = {v1.0.0},
  year      = {2026},
  publisher = {Zenodo},
  doi       = {10.5281/zenodo.22857985},
  url       = {https://doi.org/10.5281/zenodo.22857985}
}
```

---

## Contents

| Path | What it is |
| --- | --- |
| `backend/` | FastAPI application, Celery workers, pRESTO wrappers, single-cell adapters, automated tests, Dockerfile |
| `frontend/` | React / TanStack Start web interface |
| `paper/manuscript/` | The submission package: `main.tex`, `supplementary.tex`, the OUP class file and every figure |
| `paper/test/` | Validation scripts and their reports |
| `paper/benchmark/` | Benchmark harness, the reference command-line scripts and every replicate time |
| `paper/EXPECTED_OUTPUTS.sha256` | SHA-256 and size of every archived validation output |
| `paper/INPUT_DATASETS.sha256` | SHA-256 and size of every public input file the validation uses |
| `release-artifacts/` | The bulky archived outputs, as compressed archives with their own checksums — attach these to the tagged release rather than committing them |
| `LICENSE` | GNU Affero General Public License v3.0 |
| `THIRD_PARTY_NOTICES.md` | Every redistributed dependency and its licence |
| `SECURITY.md` | Threat model, operator responsibilities, secrets and data retention |
| `CHANGELOG-REVISION.md` | What changed for the second-round revision, item by item |

---

## Licence

AIRRPrep is released under the **GNU Affero General Public License, version 3
or later** (`LICENSE`). That is not a free choice: `backend/app/presto_tools/`
contains modified copies of pRESTO's tools, pRESTO is AGPL-3.0, and AIRRPrep
is offered over a network, so the AGPL's network clause applies to the hosted
service as well. Every other redistributed dependency is under a permissive or
AGPL-compatible licence; see `THIRD_PARTY_NOTICES.md`.

USEARCH is proprietary and is **not** redistributed here or in the container
image. Nothing defaults to it, and no predefined workflow needs it.

---

## Reproducing everything in the manuscript

### 1. Set up

```bash
git clone https://github.com/ComputImm/AIRRPrep.git
cd AIRRPrep/backend
python -m venv venv
venv/bin/pip install -r requirements.txt          # venv\Scripts\pip on Windows
```

External tools the bulk validation needs on `PATH` (or named through the
environment variables in `app/config.py`): `blastn`, `makeblastdb`, `vsearch`,
`muscle`, `cd-hit-est`. The container image installs all of them; see
`docker/README.md`.

### 2. Run everything

```bash
# Automated test suite (93 tests, no external tool, no Redis, no network)
cd backend && venv/bin/python -m unittest discover -s tests -v

# Per-operation comparison with native pRESTO (Supplementary Table S2)
cd ../paper/test/component_matrix
python run_component_matrix.py                    # writes component_matrix.{tsv,json}
python run_usearch_clustersets.py                 # separate USEARCH test (needs a licence)

# Single-cell record-level validation (Supplementary Tables S6, S7)
cd .. && python validate_singlecell.py            # writes validation_report.{tsv,json}
python validate_trust4.py                         # writes trust4_validation.{tsv,json}

# Runtime comparison (Supplementary Tables S8, S9)
cd ../benchmark && python benchmark.py            # writes results.json
```

Input files are not redistributed: they are the public datasets named in the
manuscript's Data availability section. `paper/INPUT_DATASETS.sha256` gives the
SHA-256 of each one, so a download can be checked before it is used.

### 3. Check the result

Every archived output has a recorded checksum:

```bash
cd paper && sha256sum -c EXPECTED_OUTPUTS.sha256
```

---

## Which script produces which table

| Manuscript item | Script | Result file |
| --- | --- | --- |
| Supplementary Table S2 (47-case component matrix) | `paper/test/component_matrix/run_component_matrix.py` | `component_matrix.tsv`, `component_matrix.json` |
| Supplementary Table S2, separate USEARCH test | `paper/test/component_matrix/run_usearch_clustersets.py` | `usearch_clustersets.tsv`, `usearch_clustersets.json` |
| Supplementary Tables S3–S5 (per-step record counts, bulk) | `paper/benchmark/compare_records.py` with `cli_race.sh`, `cli_nonumi.sh`, `cli_umi.sh` | `records_verified.json`, `records_verified.txt` |
| Supplementary Table S6 (Cell Ranger, record level) | `paper/test/validate_singlecell.py` | `validation_report.tsv`, `validation_report.json` |
| Supplementary Table S7, G1–G4 (generic FASTA) | `paper/test/validate_singlecell.py` | `validation_report.tsv`, `validation_report.json` |
| Supplementary Table S7, T1–T4 and negatives | `paper/test/validate_trust4.py`, `paper/test/trust4-test/` | `trust4_validation.tsv`, `trust4_validation.json` |
| Supplementary Table S8 (runtime, overall and per step) | `paper/benchmark/benchmark.py`, `export_table_s8.py` | `results.json` |
| Supplementary Table S9 (parameters and reference scripts) | `paper/benchmark/make_table_s9.py`, `cli_*.sh` | printed to the supplement |
| Supplementary Table S10 (environment) | `paper/benchmark/benchmark.py` environment capture; `docker/make-tool-versions.sh` | `results.json`, `docker/tool-versions.md` |
| Supplementary Note S1 (validator, 3 accepted / 14 refused) | `backend/tests/test_workflow_validation.py` | test output |
| Lossless annotation provenance | `backend/tests/test_source_annotations.py`, `paper/test/validate_singlecell.py` | test output, `validation_report.json` |
| Refusals (Supplementary Table S7 negatives) | `backend/tests/test_negative_inputs.py` | test output |
| Security controls (Supplementary Note S2) | `backend/tests/test_security_controls.py` | test output |
| USEARCH not redistributed (Supplementary Table S10) | `backend/tests/test_no_proprietary_binaries.py` | test output |

---

## Running the service

```bash
cd backend
cp .env.example .env        # then set the values SECURITY.md lists as required
docker compose up --build
```

The image builds TRUST4 from source and installs BLAST+, samtools, MUSCLE 3,
VSEARCH and CD-HIT from Debian packages. The resolved version of every one of
them is written into the image at build time as `/app/TOOL_VERSIONS.txt`, so
the versions an image actually contains can be read back from that image:

```bash
docker run --rm airrprep-backend cat /app/TOOL_VERSIONS.txt
```

A deployment that holds a USEARCH licence can mount its own binary:

```bash
docker run -v /opt/usearch:/opt/usearch:ro -e USEARCH_BIN=/opt/usearch/usearch ...
```

---

## Building the submission package

```bash
cd paper/manuscript
python build_submission_package.py     # writes AIRRPrep-submission.zip
```

The ZIP contains `main.tex`, `supplementary.tex`, `oup-authoring-template.cls`
and every figure, and nothing else — it compiles from a newly created empty
directory with pdfLaTeX.
