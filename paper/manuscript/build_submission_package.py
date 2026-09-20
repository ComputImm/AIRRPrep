"""
Build the submission ZIP for the manuscript, and nothing else.

    cd paper/manuscript
    python build_submission_package.py

The ZIP contains exactly the files needed to compile `main.tex` and
`supplementary.tex` from a newly created empty directory:

    main.tex
    supplementary.tex
    oup-authoring-template.cls
    figure1_workflow.pdf
    figure2_bulk_lanes.pdf
    supp_fig_S1_single_cell_workflow.png
    supp_fig_S2_paired_read_workflow.png
    supp_fig_S3_read_retention.png
    README.txt

Nothing else: no working copies, no superseded drafts, no build logs, no
auxiliary files, no unreferenced figures. The build fails rather than writes a
ZIP if any of those files is missing, if a file in the directory is not on the
list, or if a `\\includegraphics` in either source names a file the ZIP does
not carry.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ZIP_NAME = "AIRRPrep-submission.zip"

#: Exactly what the package contains, in the order a reader meets it.
CONTENTS = [
    "README.txt",
    "main.tex",
    "supplementary.tex",
    "oup-authoring-template.cls",
    "figure1_workflow.pdf",
    "figure2_bulk_lanes.pdf",
    "supp_fig_S1_single_cell_workflow.png",
    "supp_fig_S2_paired_read_workflow.png",
    "supp_fig_S3_read_retention.png",
]

#: Files that live here for the build itself and are not part of the package.
NOT_SHIPPED = {ZIP_NAME, Path(__file__).name}


def graphics_referenced(source: Path) -> set[str]:
    text = source.read_text(encoding="utf-8")
    return set(re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", text))


def main() -> int:
    problems: list[str] = []

    missing = [name for name in CONTENTS if not (HERE / name).is_file()]
    if missing:
        problems.append("missing from the directory: " + ", ".join(missing))

    extra = sorted(
        p.name for p in HERE.iterdir()
        if p.is_file() and p.name not in CONTENTS and p.name not in NOT_SHIPPED
    )
    if extra:
        problems.append(
            "present but not part of the package (remove them, or add them to "
            "CONTENTS): " + ", ".join(extra)
        )

    for source in ("main.tex", "supplementary.tex"):
        path = HERE / source
        if not path.is_file():
            continue
        for figure in sorted(graphics_referenced(path)):
            if figure not in CONTENTS:
                problems.append(f"{source} includes {figure}, which the ZIP does not carry")

    # The reviewer's own gate: no placeholder may survive into the package.
    # Markers, not the English word: the supplement legitimately describes
    # ENA's constant "placeholder quality" string, and this README explains
    # the check itself.
    placeholder = re.compile(
        r"\bTODO\b|\bFIXME\b|\bTBD\b|\bPLACEHOLDER\b"                 # markers
        r"|to be (?:completed|confirmed|assigned|determined|added)"   # prose stubs
        r"|DOI HERE"
        r"|\[\s*(?:tag|sha|SHA|commit|DOI|licen[cs]e|Zenodo)[^\]]*\]"  # bracketed dummies
        r"|sha256:\s*\\?ldots"
        r"|XXXX"
    )
    for source in ("main.tex", "supplementary.tex", "README.txt"):
        path = HERE / source
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if placeholder.search(line):
                problems.append(f"{source}:{number} still contains a placeholder: {line.strip()[:70]}")

    if problems:
        print("Package not built:\n  - " + "\n  - ".join(problems), file=sys.stderr)
        return 1

    target = HERE / ZIP_NAME
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in CONTENTS:
            archive.write(HERE / name, arcname=name)

    total = sum((HERE / name).stat().st_size for name in CONTENTS)
    print(f"{target.name}  {target.stat().st_size / 1e6:.2f} MB "
          f"({len(CONTENTS)} files, {total / 1e6:.2f} MB uncompressed)")
    for name in CONTENTS:
        print(f"  {(HERE / name).stat().st_size:>9,}  {name}")
    print(
        "\nClean-room test: extract this ZIP into a new empty directory and run\n"
        "  pdflatex main.tex && pdflatex main.tex\n"
        "  pdflatex supplementary.tex && pdflatex supplementary.tex\n"
        "Nothing outside that directory should be required."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
