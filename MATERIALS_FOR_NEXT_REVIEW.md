# Materials for the next review

The reviewer's *Second Round Revision Requirements* asks for a specific set of
materials to be returned together. This file says, for each one, where it is —
and, where something is not here, says so plainly rather than leaving it to be
discovered.

| Requested | Status | Where |
| --- | --- | --- |
| A clean manuscript ZIP that compiles from an empty directory | **Here** | `paper/manuscript/AIRRPrep-submission.zip` — 9 files, nothing else; built by `build_submission_package.py`, which refuses to write a ZIP that is not clean |
| Compiled `main.pdf` and `supplementary.pdf` from that exact ZIP | **Not here** | No LaTeX distribution was available on the machine this revision was prepared on. Extract the ZIP into a new empty directory and run pdfLaTeX twice per document, or upload the ZIP to Overleaf. |
| The public repository URL | **Here** | `https://github.com/ComputImm/AIRRPrep` (see the note below) |
| Release tag and commit SHA | **Not here** | Produced by tagging the release; see "What still has to be done on a server" |
| Licence | **Here** | `LICENSE` — GNU AGPL v3.0-or-later, with the reasoning in `THIRD_PARTY_NOTICES.md` |
| Zenodo DOI | **Not here** | Requires a Zenodo deposit; see below |
| Immutable container image reference including the full sha256 digest | **Not here** | Requires pushing the image to a registry; see below. The build itself, and the manifest of every tool version it resolves, are here: `backend/Dockerfile`, `docker/README.md`, `docker/make-tool-versions.sh` |
| All test and validation artifacts of Item 2 | **Here** | `paper/test/`, `paper/benchmark/`, `paper/EXPECTED_OUTPUTS.sha256`, `paper/INPUT_DATASETS.sha256`, and the three archives in `release-artifacts/` |
| A change log mapping Items 1–8 to the files and sections changed | **Here** | `CHANGELOG-REVISION.md` |
| A machine-readable summary of which automated tests passed | **Here** | `paper/TEST_SUMMARY.json` |

---

## What still has to be done on a server, and in what order

None of the four items below can be produced from a source tree; each needs an
account or a host. They are listed in the order they have to happen, because
each one's output is the next one's input.

1. **Push and tag.** Push this tree to `github.com/ComputImm/AIRRPrep` and tag
   the commit the manuscript describes. Record the tag and the full commit SHA.
2. **Build and push the image.**
   ```bash
   docker/make-tool-versions.sh ghcr.io/computimm/airrprep-backend:<tag>
   docker push ghcr.io/computimm/airrprep-backend:<tag>
   docker image inspect --format '{{index .RepoDigests 0}}' \
       ghcr.io/computimm/airrprep-backend:<tag>
   ```
   Commit the `docker/tool-versions.md` the script writes; it will then also
   carry the registry digest.
3. **Archive on Zenodo.** Create a deposit from that exact tag and record the
   DOI. Attach the three files in `release-artifacts/` as deposit files, so the
   bulky evidence is archived with the code rather than only in a Git
   repository.
4. **Set `AIRRPREP_IMAGE`** on the deployment to the image digest, so every
   run's `provenance.json` records which image produced it.

### Where those four values go, once they exist

The manuscript is written so that it is **complete and free of placeholders
without them** — the Data availability section describes the repository, its
contents and its licence, and claims nothing that depends on a tag, a DOI or a
digest. That was deliberate: a placeholder is worse than an omission. If the
journal asks for them, or you would rather cite them, add them in exactly
these three places:

* `paper/manuscript/main.tex`, Data availability — after "available at
  \\url{...}", add "as release `<tag>` (commit `<sha>`), archived at
  `<Zenodo DOI>`; the container image is `<registry>@sha256:<digest>`".
* `paper/manuscript/supplementary.tex`, Supplementary Table S10, the
  "Deployment container image" block — add a "Image digest" row.
* `README.md` — add the tag and DOI beside the repository URL.

Re-run `python build_submission_package.py` afterwards; it will re-check that
nothing you added reads as a placeholder.

---

## Two things the authors must check, not verify

These are editorial, not evidential, and were drafted rather than measured:

1. **Author contributions** (`main.tex`, §Author contributions) — a CRediT
   statement drafted from the visible record. Correct it.
2. **Funding** (`main.tex`, §Funding) — written as an explicit
   no-specific-funding statement. Confirm or replace it.

The affiliation is spelled **ComputImm**, matching the organisation's own site
and GitHub account. If the legal entity name differs, change it in `main.tex`.

---

## One reviewer point that was checked and not acted on

Item 7 asks for the typo "Strip ahnotation fields" to be corrected in
Supplementary Figure S1. **The figure does not contain that typo.** The
rendered PNG reads "Strip annotation fields"; this was verified by inspecting
`paper/manuscript/supp_fig_S1_single_cell_workflow.png` directly. Nothing was
"fixed", because there was nothing wrong.

The figure was nevertheless re-exported from the running application, for a
different reason: it now shows `source_annotations.tsv` as a third output and
states that the stripped fields are kept there, so that the figure, the
caption and the implementation say the same thing (Item 3).
