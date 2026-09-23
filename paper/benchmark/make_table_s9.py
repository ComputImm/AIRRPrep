# -*- coding: utf-8 -*-
"""
Generate Supplementary Table S9 (per-step execution time) from table_s8.json
and insert it into paper/our_edit/supplementary.tex before \\end{document}.

Re-running replaces an existing S9 section rather than appending a second one,
so this can be run again after a new benchmark round.
"""

import json
import re
from pathlib import Path

BENCH = Path(__file__).resolve().parent
TEX = BENCH.parents[2] / "paper" / "our_edit" / "supplementary.tex"

BS = chr(92)          # a single backslash, kept out of the f-strings below
NL = BS + BS          # LaTeX row terminator


def esc(text):
    """Escape the few LaTeX-significant characters our labels can contain."""
    return text.replace("_", BS + "_").replace("%", BS + "%").replace("&", BS + "&")


def prime(label):
    return label.replace("5'", "5$'$ ")


def rows(workflow):
    out = []
    for s in workflow["steps"]:
        label = esc(re.sub(r"^(\d+)\s+", r"\1. ", s["label"].strip()))
        cli, ap = s["cli_s"], s["ap_s"]
        cli_txt = f"{cli:.1f}" + (BS + "dag" if s["cli_derived"] else "")
        ap_txt = f"{ap:.1f}" + (BS + "ddag" if s["ap_derived"] else "")
        ratio = f"{cli / ap:.2f}" + BS + "times" if ap else "--"
        out.append(f"{label} & {ap_txt} & {cli_txt} & ${ratio}$ {NL}")
    return "\n".join(out)


def block(workflow):
    total_cli = sum(s["cli_s"] for s in workflow["steps"])
    total_ap = sum(s["ap_s"] for s in workflow["steps"])
    name = prime(workflow["label"])
    return f"""
{BS}subsection*{{{esc(name)}}}

{BS}begin{{center}}
{BS}begin{{tabular}}{{p{{0.40{BS}textwidth}}ccc}}
{BS}toprule
{BS}textbf{{Step}} &
{BS}textbf{{AIRRPrep (s)}} &
{BS}textbf{{CLI-pRESTO (s)}} &
{BS}textbf{{Ratio}}
{NL}
{BS}midrule
{rows(workflow)}
{BS}midrule
{BS}textit{{Total}} & {BS}textit{{{total_ap:.1f}}} & {BS}textit{{{total_cli:.1f}}} &
${BS}textit{{{total_cli / total_ap:.2f}}}{BS}times$ {NL}
{BS}bottomrule
{BS}end{{tabular}}
{BS}end{{center}}
"""


def main():
    data = json.loads((BENCH / "table_s8.json").read_text())
    body = "".join(block(w) for w in data["workflows"])

    section = f"""
{BS}clearpage
{BS}section*{{Supplementary Table S9. Execution time by processing step}}

Per-step wall-clock time for both implementations, from one replicate of each
workflow. Steps follow the numbering of Supplementary Tables~S2--S4, which
report the record counts retained at each one and at which both implementations
agreed throughout; the final annotation-table export is not listed there and is
included here so that the steps account for the whole runtime. Ratio is
CLI-pRESTO time divided by AIRRPrep time, so
values above one favour AIRRPrep. Totals are the sum of the steps of the single
replicate shown and therefore differ from the three-replicate means reported in
Supplementary Table~S8, which are the values to cite for overall runtime.

Two steps leave no timestamp of their own and are recovered as the residual of
the run, that is, the measured total of that replicate minus every step that
could be timed: {BS}dag~the first command-line step, because the inputs are copied
into the run directory and a copy preserves the source modification time, and
{BS}ddag~the last AIRRPrep step, whose output is written to the job output
directory rather than to a numbered step directory. Each residual absorbs any
unattributed overhead and is therefore an upper bound on that step. Where the
recovery can be checked it holds: in the two workflows whose first and second
steps are the same operation on opposite mate streams, the recovered first
step falls within 2{BS}% of the measured second step.
{body}"""

    tex = TEX.read_text(encoding="utf-8")
    marker = BS + "clearpage" + chr(10) + BS + "section*{Supplementary Table S9"
    if marker in tex:
        tex = tex[:tex.index(marker)] + BS + "end{document}" + chr(10)
    end = BS + "end{document}"
    tex = tex.replace(end, section.rstrip() + chr(10) + chr(10) + end)
    TEX.write_text(tex, encoding="utf-8")
    print("Table S9 written:", sum(len(w["steps"]) for w in data["workflows"]), "steps")


if __name__ == "__main__":
    main()
