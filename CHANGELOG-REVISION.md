# Second-round revision — what changed, item by item

Reviewer document: *AIRRPrep Second Round Revision Requirements*, 18 September
2026. Each of its eight items is answered below with the exact files and
sections changed. Paths are relative to this repository unless they name a
file in the working tree.

---

## Item 1 — Correct the component validation result *(blocker)*

**What was wrong.** The main text said 46 of 47 operations produced identical
output and then described two native pRESTO failures as if both were
exceptions inside the same 47-case comparison. The supplement said every
operation behaves identically, which cannot be true of one that could not be
compared, and it did not say which clustering backend each `ClusterSets` case
used.

**What changed.**

* The 47 cases now carry exactly two statuses: `identical` (46) and
  `not comparable (native pRESTO failed)` (1). The word "identical" is no
  longer used of the 47th case anywhere.
* The three `ClusterSets` cases of the matrix are stated to use **VSEARCH**,
  the open tool the image carries. The **USEARCH** test is a separate,
  additional test, in its own script and its own report, and is explicitly
  outside the 47-case denominator.
* `ConvertHeaders.py migec` is described as *not comparable*, with the reason
  (native pRESTO raises `Duplicate key 'MIG'` and writes nothing), not as
  agreement.
* The USEARCH claim was re-measured and narrowed to what the evidence
  supports: native pRESTO's generated command line is rejected by USEARCH
  (`Unknown option minwordmatches`), and AIRRPrep's is accepted. Carrying it
  through to an output comparison is not possible on Windows, for the same
  open-temporary-file reason the VSEARCH cases run in a Linux container, and
  a licensed Linux USEARCH binary cannot be shipped with the test suite. That
  limitation is now stated rather than glossed.

| File | Change |
| --- | --- |
| `paper/manuscript/main.tex` | Abstract, Validation §; new sentences on the denominator and the separate USEARCH test |
| `paper/manuscript/supplementary.tex` | Table S2 intro, footnote a, caption, "Result", "The one case that could not be compared", new subsection "Separate test: ClusterSets with USEARCH" |
| `paper/test/component_matrix/run_component_matrix.py` | Per-case `denominator`; outcome renamed to `not comparable (native pRESTO failed)`; POSIX paths in the report |
| `paper/test/component_matrix/run_usearch_clustersets.py` | **New.** The separate USEARCH test |
| `paper/test/component_matrix/component_matrix.{tsv,json}` | Regenerated |
| `paper/test/component_matrix/usearch_clustersets.{tsv,json}` | **New** |
| `README.md` | Table-to-script map reports the same denominator |

The component matrix now has one row per case with: `operation`,
`denominator`, `input`, `parameters`, `native_command`, `airrprep_command`,
`comparator`, `status`, `native_output_sha256`, `airrprep_output_sha256`.

---

## Item 2 — Release the complete reproducibility package *(blocker)*

| Required | Where it is |
| --- | --- |
| Explicit open-source licence | `LICENSE` (AGPL-3.0), `THIRD_PARTY_NOTICES.md` |
| `paper/test/validate_singlecell.py` + reports | `paper/test/validate_singlecell.py`, `validation_report.{tsv,json}` |
| `paper/test/validate_trust4.py`, its container, expected outputs, checksums | `paper/test/validate_trust4.py`, `paper/test/trust4-test/`, `trust4_validation.{tsv,json}`, `paper/EXPECTED_OUTPUTS.sha256` |
| Component matrix + harness + archived outputs | `paper/test/component_matrix/` and `release-artifacts/component-matrix-archive.tar.gz` |
| Bulk comparator, shell scripts, primer provenance, subsetting commands | `paper/benchmark/compare_records.py`, `cli_race.sh`, `cli_nonumi.sh`, `cli_umi.sh`, `paper/benchmark/inputs/`, `verify_inputs_ena.py` |
| `benchmark.py`, every replicate, environment capture | `paper/benchmark/benchmark.py`, `results.json` |
| Automated negative tests | `backend/tests/test_negative_inputs.py` (**new**), `backend/tests/test_workflow_validation.py` |
| Top-level README with one command sequence and a table→script map | `README.md` |

**New test files**

* `backend/tests/test_negative_inputs.py` — FASTA with no barcode rule, a
  mapping that misses a sequence, a header rule that matches nothing, an
  invalid regex, a BAM whose CB/UB tags cannot be used (both routes, neither
  falling back to a barcode-free assembly), a contig-aligned BAM, a BAM with no
  references, four mismatched TRUST4 pairings, and a guard on the
  3-accepted/14-refused workflow set.
* `backend/tests/test_source_annotations.py` — the lossless-provenance join.
* `backend/tests/test_security_controls.py` — Item 8's security list.
* `backend/tests/test_no_proprietary_binaries.py` — Item 8's USEARCH list.
* `backend/tests/_fakeredis.py` — in-memory Redis with an injectable clock, so
  expiry is tested without a server and without sleeping.

The suite is 93 tests and needs no Redis, no external tool and no network.

**Checksums.** `paper/EXPECTED_OUTPUTS.sha256` gives the SHA-256 and size of
every archived validation output; `paper/INPUT_DATASETS.sha256` does the same
for the public inputs, which are not redistributed.

---

## Item 3 — Preserve upstream annotation provenance *(blocker)*

The preferred route was implemented: **a lossless sidecar**, not a weakened
claim.

Every single-cell run now writes `source_annotations.tsv` beside
`final.fasta` and `metadata.tsv`. It holds every field the uploaded file
carried for a record — including the V(D)J calls, junctions and CDR3s the
normalized schema omits — keyed on the same source `sequence_id`, with the
source's own column order and including a column that is empty in every row.
Its SHA-256 goes into `provenance.json` beside the inputs'.

| File | Change |
| --- | --- |
| `backend/app/singlecell/adapters/base.py` | `record_source_annotation()`, `_adopt_source_annotations()` and the three fields they fill |
| `backend/app/singlecell/adapters/cellranger_adapter.py` | Captures the contig CSV row and the AIRR TSV row before stripping |
| `backend/app/singlecell/adapters/generic_fasta_adapter.py` | Captures the FASTA header and the full mapping-file row |
| `backend/app/singlecell/adapters/trust4_adapter.py` | Captures the `annot.fa` header, the barcode-report row and the `barcode_airr` row |
| `backend/app/singlecell/adapters/{fastq,bam}_adapter.py` | Carry the inner adapter's sidecar out |
| `backend/app/singlecell/fasta_generator.py` | `write_source_annotations()` |
| `backend/app/singlecell/tasks.py` | Writes it, records it in `provenance.json`, exposes it on the job |
| `frontend/src/api/singleCell.ts`, `components/SingleCellProgress.tsx`, `routes/single-cell.$formatId.tsx` | Download buttons for the sidecar and for `provenance.json` |
| `frontend/src/lib/singleCellDocs.ts` | The in-app workflow diagram lists the sidecar as an output and says the stripped fields are kept in it |
| `backend/tests/test_source_annotations.py` | **New.** Join is total, one-to-one, collision-free; the omitted fields are present with the source's values |
| `paper/test/validate_singlecell.py` | Checks the same join on the real 10x data and reports it |

**Result on real data** (10x `sc5p_v2_hs_PBMC_10k`): 15,377 / 10,817 / 10,817
sidecar rows for the three Cell Ranger routes, 18 / 18 / 32 source columns
preserved, **0** rows unjoinable in either direction, 0 duplicate identifiers.

Manuscript: the sentence equating a checksum with preservation is gone.
`main.tex` §Single-cell normalization and the Abstract now describe the
sidecar; Supplementary Table S1's note, Supplementary Figure S1's caption,
Table S6 (three new rows and footnote b) and Table S7 report it.

---

## Item 4 — Benchmark scope and platform limitation *(major)*

The alternative route was taken, deliberately: the Windows experiment is kept
and **every** performance claim is narrowed to it. A resource-matched Linux
benchmark at production input sizes has not been run, and nothing in the paper
now depends on one.

* The `TODO(revision C7/C8)` comment in `supplementary.tex` is removed,
  because the route was chosen and carried out.
* Abstract: "On one Windows 11 workstation, using 25,000-read-pair subsets,
  AIRRPrep completed the three workflows 1.2–2.8 times faster than
  command-line pRESTO; these measurements quantify small-input execution
  overhead rather than production-scale throughput."
* Results §: the same qualification, plus an explicit statement that no
  platform-independent or production-scale advantage is claimed.
* Discussion: the margins are described as small-input execution overhead on
  one Windows workstation, not throughput at production scale or on the Linux
  hosts a containerized deployment would normally use; a resource-matched
  Linux benchmark is named as future work.
* Supplementary Table S8 opens with a "Scope of this comparison" paragraph
  saying the same thing, and the S8a caption ends with "These ratios describe
  this host and this input size only."

---

## Item 5 — One clean, self-contained submission package *(blocker)*

`paper/manuscript/` is the package, and it is built by a script that refuses
to produce a ZIP unless it is clean.

* The authoritative sources are `main.tex` and `supplementary.tex`. There is
  no `main2.tex`, no `supplementary2.tex`, no `sub.tex` and no
  `article_source_original_full.md`; the superseded drafts do not enter the
  package.
* `oup-authoring-template.cls` (OUP's class, LPPL-1.3+, from CTAN) is
  included, so the package compiles from a newly created empty directory.
* The obsolete narrow Supplementary Figure S3 is gone. The actual read-retention
  export is the file the LaTeX references, renamed to
  `supp_fig_S3_read_retention.png`; `sequence-retention-2026-09-17.png` no
  longer appears anywhere.
* `README.txt` lists exactly the files present, names the engine and the
  number of passes, lists the LaTeX packages each document needs, and states
  that there is no `.bib` file.
* `build_submission_package.py` fails the build if a listed file is missing,
  if the directory holds a file that is not part of the package, if either
  source includes a figure the ZIP does not carry, or if any source still
  contains a placeholder.

**Not done here:** compiled `main.pdf` and `supplementary.pdf` are not in the
package, because no LaTeX distribution was available on the machine this
revision was prepared on. Extract `AIRRPrep-submission.zip` into an empty
directory and run pdfLaTeX twice per document, or upload the ZIP to Overleaf.

---

## Item 6 — Replace all submission placeholders *(blocker)*

| Placeholder | Now |
| --- | --- |
| `\DOI{DOI HERE}` | Removed. The class defaults it to empty; the journal's production system supplies it. |
| `\access{Advance Access Publication Date: Day Month Year}` | Removed, same reason |
| `\received{Date}{0}{2026}` etc. | Removed, same reason |
| `[LICENCE -- to be confirmed]` | **GNU Affero General Public License v3.0 or later**, stated in the Abstract and in Data availability, with `LICENSE` and `THIRD_PARTY_NOTICES.md` in the repository |
| `[tag]`, `[SHA]`, `[Zenodo DOI -- to be assigned]`, `[registry/image@sha256:digest]` | Replaced with the real values, now that they exist. Data availability names release `v1.0.0` (commit `9148dba8bdd4c516b80db4eece07dd0a0b23a929`) and the Zenodo DOI `10.5281/zenodo.22857985`; the Abstract's *Availability and Implementation* line carries the DOI too. The container image digest is still not named, because the image has not been pushed to a registry — see the note below. |
| Supplementary Table S10 `[sha256:...]` | Replaced. The image build records the resolved version of every Debian-packaged tool inside the image as `/app/TOOL_VERSIONS.txt`, so the contents of an image can be read back from it; `docker/make-tool-versions.sh` writes that manifest out for a release. |
| `[To be completed: contribution statement per author.]` | CRediT statement per author — **please check and correct before submission**, see "Needs author confirmation" below |
| `[To be completed.]` (Funding) | "No specific funding was received for this work." — **please confirm** |
| `Computimm` | `ComputImm`, with the OUP affiliation macros (`\author[1]{…}`, `\address[1]{\orgname{…}, \orgaddress{\state{…}, \country{…}}}`) |
| README "authors and contact remain placeholders" | Gone; the README describes what is actually in the package |

A case-insensitive search of the final manuscript package for `TODO`,
`FIXME`, `TBD`, `PLACEHOLDER`, "to be completed/confirmed/assigned/determined
/added", `DOI HERE`, bracketed dummies and `XXXX` returns nothing;
`build_submission_package.py` runs that search on every build and refuses to
write a ZIP that fails it.

### Tag, commit and DOI — added after the first pass

The release now exists, so the three values that were deliberately omitted are
stated rather than described:

| Value | Where it is recorded |
| --- | --- |
| Tag `v1.0.0` | `main.tex` Data availability; `README.md`; `CITATION.cff` |
| Commit `9148dba8bdd4c516b80db4eece07dd0a0b23a929` | the same three |
| Zenodo DOI `10.5281/zenodo.22857985` (version) and `10.5281/zenodo.22857984` (all versions) | `main.tex` Data availability and Abstract; `README.md` badge, *Release and citation* section and BibTeX entry; `CITATION.cff` |

`CITATION.cff` is new: it is what GitHub's *Cite this repository* button reads,
so the DOI is discoverable from the repository page itself and not only from
the manuscript.

The **container image digest remains unstated**. The image has not been pushed
to a registry, so there is no digest to name; Supplementary Table S10 still
describes the build and the in-image `TOOL_VERSIONS.txt` manifest instead. That
is an omission, not a placeholder, and `build_submission_package.py` passes.

The same search over the repository returns only `TODO` comments inside
`backend/app/presto_tools/`, which are pRESTO's own, in the upstream source
AIRRPrep vendors; they are not ours to remove. AIRRPrep's own code has none.
The one that was ours — a stale note in `requirements.txt` saying pysam would
be added "once BamAdapter is wired to real CB/UB extraction" — contradicted
the adapter, which deliberately does not use pysam, and has been replaced by
a statement of that decision.

### Needs author confirmation

Two things in this revision are editorial drafts, not derived from evidence,
and must be checked by the authors before submission:

1. **Author contributions.** A CRediT statement was drafted from the visible
   record (authorship order, corresponding author, repository history, in
   which Fatemeh Chaker Hosseini Zavareh is by far the largest contributor).
   It is a reasonable first draft, not a statement of fact — correct it.
2. **Funding.** Written as an explicit no-specific-funding statement. If any
   grant supported the work, replace it.
3. **Affiliation.** Spelled `ComputImm`, matching the organisation's own site
   and its GitHub account. If the legal entity name differs (for example
   "ComputImm Lab"), change it. No second affiliation was added for any
   author, because none was stated in the previous version.

---

## Item 7 — Figures, terminology and supplementary layout *(major)*

| Required | Done |
| --- | --- |
| "ahnotation" → "annotation" in Supplementary Figure S1 | **No such typo exists.** The rendered PNG reads "Strip annotation fields"; verified by inspecting `supp_fig_S1_single_cell_workflow.png` directly. The figure *was* re-exported from the application, for a different reason: it now shows `source_annotations.tsv` as a third output and says the stripped fields are kept there (Item 3). The spelling was correct before and after. |
| Rename the read-retention export, remove the obsolete duplicate | Done. `supp_fig_S3_read_retention.png` is the current export; the clipped narrow version is not in the package |
| "read stream" instead of "lane" in figures | The figure's own labels already say "read stream"; the caption's stale disclaimer about "lane" is replaced by a positive statement that read streams are called R1 and R2 throughout and that a flow-cell lane is never meant. "lane" survives only as an internal identifier in source code, never in rendered output |
| `AssembleSeq` ↔ `AssemblePairs.py` mapping visible in the caption and applied consistently | The mapping is now in the Supplementary Figure S4 caption as well as in the Table S2 note, and the component matrix records both names per case |
| Every figure filename matches across README, LaTeX, ZIP and caption | Enforced by `build_submission_package.py` |
| Reformat Supplementary Tables S10 and S11 | Both are now `longtable` inside `landscape`, with repeated headers; S10's column widths were rebalanced |
| Long URLs, filenames, checksums and paths break without entering the margin | `xurl` in both documents, `seqsplit` available in the supplement, `\emergencystretch` and `\sloppy` set |
| No overfull table or clipped paragraph; no overlap of page numbers, borders, captions or footnotes | The two tables that overflowed are landscape longtables, so neither runs past the text block or into the footer. **This has not been checked in a rendered PDF**, for the reason given under Item 5 |

---

## Item 8 — Security and USEARCH verified against the released code *(major)*

### Security

`backend/tests/test_security_controls.py` (**new**, 23 tests) asserts every
statement Supplementary Note S2 makes:

* code expiry, and that a wrong guess does not extend it;
* the attempt limit burns the code, so even the correct one stops working;
* the resend cooldown, and that a resend after it replaces the old code;
* codes stored only as a SHA-256 salted with the session id;
* address normalisation on storage, comparison and recovery, and refusal of
  malformed addresses;
* the tracking record holds a keyed HMAC-SHA256, not the address and not a
  bare SHA-256;
* wrong code and wrong address are indistinguishable;
* the recovery URL carries the code and never the address;
* the recovery route is CAPTCHA-gated *before* the lookup and rate limited,
  sending a code is limited more tightly, and a CAPTCHA is consumed on first
  use whether the answer was right or wrong;
* tracking records expire and can be refreshed while a run is watched.

`SECURITY.md` (**new**) documents the retention and deletion behaviour of the
plain-text addresses on session and job records, and lists the operator's
responsibilities — `EMAIL_HASH_SECRET`, `REDIS_PASSWORD`, SMTP over TLS, TLS
termination and `X-Forwarded-*`, `ALLOWED_ORIGINS`, the limits, and the
privacy notice a public instance needs.

### USEARCH

`backend/tests/test_no_proprietary_binaries.py` (**new**, 10 tests) asserts
that no USEARCH binary or archive is in the tree, that nothing in the
Dockerfile, the compose files, the entrypoint or the requirements installs
one, that USEARCH is reachable only through the `USEARCH_BIN` operator
setting, and that no predefined workflow needs it.

**Two defaults were changed**, because pRESTO's own defaults silently selected
USEARCH:

* `ClusterSets.*` defaulted to `usearch`; it now defaults to **vsearch**
  (`DEFAULT_CLUSTER_TOOL`).
* `AssembleSeq.reference` / `.sequential` defaulted to the `usearch` (ublast)
  aligner; they now default to **blastn** (`DEFAULT_REFERENCE_ALIGNER`).

Both are tools the image carries, so a stock deployment can run every
operation. Selecting USEARCH without a binary now fails with a message naming
the licence requirement and the open alternatives.

**A related hole was closed while verifying this.** `AssembleSeq.reference`
and `.sequential` accepted `aligner_exec` and `db_exec` as *step parameters*,
so a request could name which executable the worker runs — exactly what
`app/config.py` says must never happen, and what is already prevented for
MUSCLE and the clustering tools. Both parameters are gone from the wrapper
signatures; the binaries are resolved from `BLASTN_BIN` / `MAKEBLASTDB_BIN` /
`USEARCH_BIN` in the configuration. A test asserts that no wrapper exposes an
executable parameter.

The proprietary test is kept separate from the redistributable suite
(`run_usearch_clustersets.py`, outside `backend/tests/`), and its commands,
versions and outcome are published so the claim can be audited without a
licence.

---

## Files added

```
LICENSE
THIRD_PARTY_NOTICES.md
SECURITY.md
CHANGELOG-REVISION.md
README.md
docker/README.md
docker/make-tool-versions.sh
paper/EXPECTED_OUTPUTS.sha256
paper/INPUT_DATASETS.sha256
paper/manuscript/                          (the whole submission package)
paper/manuscript/build_submission_package.py
paper/manuscript/oup-authoring-template.cls
paper/test/component_matrix/run_usearch_clustersets.py
paper/test/component_matrix/usearch_clustersets.{tsv,json}
backend/tests/_fakeredis.py
backend/tests/test_source_annotations.py
backend/tests/test_negative_inputs.py
backend/tests/test_security_controls.py
backend/tests/test_no_proprietary_binaries.py
```

## Machine-readable test summary

`paper/TEST_SUMMARY.json` records which automated tests ran and passed when
this revision was prepared, with the counts behind each headline number.
