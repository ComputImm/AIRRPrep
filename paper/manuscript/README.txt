AIRRPrep - Bioinformatics Application Note
Submission package

FILES IN THIS PACKAGE
---------------------
  main.tex                              main manuscript (compile this first)
  supplementary.tex                     supplementary information
  oup-authoring-template.cls            OUP authoring class, required by main.tex
  figure1_workflow.pdf                  Figure 1 (main text)
  figure2_bulk_lanes.pdf                Supplementary Figure S4
  supp_fig_S1_single_cell_workflow.png  Supplementary Figure S1
  supp_fig_S2_paired_read_workflow.png  Supplementary Figure S2
  supp_fig_S3_read_retention.png        Supplementary Figure S3

Every file listed above is present, and no file in this package is unused.
There are no other manuscript sources: main.tex and supplementary.tex are the
only two documents, and there is no second copy of either under another name.

COMPILING
---------
Engine: pdfLaTeX. Each document needs two passes (three if you change a
cross-reference), because both use \ref and the supplement uses longtable.

  pdflatex main.tex
  pdflatex main.tex

  pdflatex supplementary.tex
  pdflatex supplementary.tex

Compile from a NEWLY CREATED EMPTY DIRECTORY containing only the contents of
this ZIP. Compiling inside an existing project can hide a missing dependency
that the submission system will then hit.

On Overleaf: upload this ZIP as a new project and set main.tex as the main
document; supplementary.tex compiles as a second document.

LATEX PACKAGES USED
-------------------
main.tex          graphicx, url, microtype, xurl (plus what the OUP class
                  loads: amsmath, amssymb, amsthm, natbib, hyperref, tikz,
                  tcolorbox, algorithm/algpseudocode, caption, listings,
                  rotating, wrapfig, multirow, subfloat, stfloats, flushend,
                  footmisc, crop, chngpage, silence, totcount, fix-cm,
                  mathrsfs, array, color/xcolor)
supplementary.tex geometry, graphicx, booktabs, longtable, array, url,
                  fontenc, microtype, pdflscape, xurl, seqsplit

All of these are in a full TeX Live or MiKTeX installation and on Overleaf.

BIBLIOGRAPHY
------------
References are typed directly in a thebibliography environment in main.tex.
There is no .bib file and no BibTeX/Biber pass.

NOTES
-----
* The OUP class file is included so the package compiles on its own. It is
  Oxford University Press's file, distributed under the LaTeX Project Public
  License v1.3 or later, and is not covered by AIRRPrep's own licence.
* Supplementary figure numbering is S1-S4. S1-S3 are application screenshots;
  S4 is the read-stream diagram (figure2_bulk_lanes.pdf).
* Supplementary Tables S10 and S11 are typeset landscape, so they read
  sideways in the PDF. That is intended.
* The DOI, volume, issue and publication-date fields are left to the journal's
  production system; the class supplies empty defaults for them, so nothing in
  this package has to be filled in before submission.

REBUILDING THIS PACKAGE
-----------------------
  python build_submission_package.py

The script refuses to write the ZIP if a listed file is missing, if the
directory holds a file that is not part of the package, if either source
includes a figure the ZIP does not carry, or if any source still contains a
placeholder.
