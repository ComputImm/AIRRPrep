# -*- coding: utf-8 -*-
"""
The USEARCH-specific ClusterSets test -- a separate, additional test, not one
of the 47 cases of the component matrix.

    cd paper/test/component_matrix
    ../../../presto-backend/venv/Scripts/python.exe run_usearch_clustersets.py

Why it is separate
------------------
The three ClusterSets operations are counted once each in the 47-case matrix
(run_component_matrix.py), using VSEARCH -- the open clustering tool the
container image carries and the one a stock deployment uses. USEARCH is
proprietary, is not redistributed with AIRRPrep or its image, and is the tool
for which pRESTO builds a command line that USEARCH itself rejects. It is
therefore tested here, on its own, and reported separately: including it in
the matrix would mean counting the same three operations twice and mixing a
redistributable comparison with one that cannot be re-run without a licence.

What is being established
-------------------------
1. Native pRESTO cannot run ClusterSets with USEARCH at all. pRESTO appends
   ``-minwordmatches`` to the USEARCH invocation; USEARCH v7.0.1090 -- the
   build tested here, and the series pRESTO documents for this step -- does
   not recognise the option and exits with
   ``Invalid command line / Unknown option minwordmatches``. The failure is in
   the command pRESTO constructs, so it happens for every input and cannot be
   avoided through the parameters the tool exposes.

2. AIRRPrep issues the clustering command itself and omits that option, so
   USEARCH accepts the command line and starts.

Platform note
-------------
Neither side can be carried through to an output comparison on Windows, and
for a reason that has nothing to do with USEARCH: pRESTO passes the external
tool a temporary file that Python still holds open, which Windows does not
permit, so the tool reports ``Permission denied`` on that file. The three
VSEARCH ClusterSets cases of the component matrix fail the same way and are
run in the Linux container instead (cluster-test/). Doing the same for USEARCH
would need a licensed Linux USEARCH binary, which cannot be redistributed with
the test suite, so what is reported here is what can be shown without one: the
native command line is rejected by USEARCH, AIRRPrep's is not.

Writes usearch_clustersets.json and usearch_clustersets.tsv.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

#: Per-invocation wall-clock budget. ClusterSets.set issues one clustering
#: call per barcode group, and on Windows each of those blocks on the
#: temporary file pRESTO leaves open; a run that has not finished within this
#: is reported as such rather than left to hang.
TIMEOUT_SECONDS = int(os.environ.get("USEARCH_TEST_TIMEOUT", "240"))

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
BACKEND = REPO / "presto-backend"
VENV = BACKEND / "venv" / "Scripts"

PY = Path(os.environ.get("MATRIX_PYTHON") or VENV / "python.exe")
SCRIPTS = Path(os.environ.get("MATRIX_SCRIPTS") or VENV)
USEARCH = os.environ.get(
    "USEARCH_BIN", r"C:\Tools\usearch\usearch7.0.1090_win64.exe"
)
FIXTURE = HERE / "work" / "fixtures" / "r1p" / "R1_primers-pass.fastq"
WORK = HERE / "work" / "usearch"

os.environ["USEARCH_BIN"] = USEARCH
os.environ.setdefault("WORKER_CPUS", "4")
sys.path.insert(0, str(BACKEND))

#: The three operations, with the extra arguments each one takes.
CASES = [
    ("ClusterSets.all", "all", [], {"ident": 0.9, "cluster_tool": "usearch"}),
    ("ClusterSets.barcode", "barcode", ["-f", "BARCODE"],
     {"barcode_field": "BARCODE", "ident": 0.9, "cluster_tool": "usearch"}),
    ("ClusterSets.set", "set", ["-f", "BARCODE"],
     {"set_field": "BARCODE", "ident": 0.9, "cluster_tool": "usearch"}),
]

#: What USEARCH says when it is handed pRESTO's command line, and what it says
#: when it is handed AIRRPrep's on Windows. Classifying on these strings is
#: what makes "rejected the command line" a checkable outcome rather than a
#: reading of a log.
_REJECTED = "unknown option minwordmatches"
_WINDOWS_FILE_LOCK = "permission denied"


def repo_relative(text: str) -> str:
    return text.replace(str(REPO) + os.sep, "").replace(str(REPO), ".")


def classify(output: str, returncode: int | None) -> str:
    lowered = (output or "").lower()
    if _REJECTED in lowered:
        return "command line rejected by USEARCH"
    if _WINDOWS_FILE_LOCK in lowered:
        return "command line accepted; blocked by the Windows open-file limit"
    if returncode is None:
        return (
            f"did not finish within {TIMEOUT_SECONDS}s on this host; "
            "see the platform note"
        )
    if returncode == 0:
        return "completed"
    return "failed"


def run_capturing(cmd: list[str]) -> tuple[int | None, str]:
    """Run a command, capturing output through files, with a hard timeout.

    Output goes to temporary files rather than pipes: a pRESTO step spawns
    worker processes that inherit the pipe, so on a timeout the parent can be
    killed while a grandchild still holds the write end and the read never
    returns. Files have no such handshake, and the whole process tree is
    killed by `taskkill /T` (or `Popen.kill` elsewhere).
    """
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as sink:
        proc = subprocess.Popen(cmd, stdout=sink, stderr=subprocess.STDOUT)
        try:
            returncode = proc.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            returncode = None
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.wait()
        sink.seek(0)
        return returncode, sink.read()


def run_native(sub: str, extra: list[str], outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(PY), str(SCRIPTS / "ClusterSets.py"), sub,
        "-s", str(FIXTURE), *extra,
        "--ident", "0.9", "--cluster", "usearch", "--exec", USEARCH,
        "--outdir", str(outdir), "--outname", "native", "--nproc", "1",
    ]
    started = time.time()
    returncode, combined = run_capturing(cmd)
    return {
        "command": repo_relative(
            " ".join(Path(c).name if i < 2 else c for i, c in enumerate(cmd))
        ),
        "returncode": returncode,
        "seconds": round(time.time() - started, 2),
        "usearch_message": usearch_message(combined),
        "outcome": classify(combined, returncode),
    }


def run_airrprep(step: str, params: dict, outdir: Path) -> dict:
    """AIRRPrep's own step executor, in a subprocess so a fatal exit is caught."""
    outdir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    returncode, combined = run_capturing(
        [str(PY), str(Path(__file__)), "--single-step", step,
         json.dumps(params), str(outdir)]
    )
    return {
        "command": (
            f'run_pipeline_step(SINGLE(r1={repo_relative(str(FIXTURE))}), '
            f'{{"name": "{step}", "params": '
            f'{json.dumps(params, sort_keys=True)}, "lanes": "R1"}})'
        ),
        "returncode": returncode,
        "seconds": round(time.time() - started, 2),
        "usearch_message": usearch_message(combined),
        "outcome": classify(combined, returncode),
    }


def usearch_message(output: str) -> str:
    """The lines USEARCH itself printed, without pRESTO's progress banner."""
    keep = [
        line.strip() for line in (output or "").splitlines()
        if any(
            marker in line.lower()
            for marker in ("invalid command line", "unknown option",
                           "fatal error", "cannot open", "errno")
        )
    ]
    return " | ".join(dict.fromkeys(keep))[:400]


def single_step(step: str, params: dict, outdir: Path) -> None:
    """Child-process entry point: one AIRRPrep step, nothing else."""
    from app.pipeline.executor import run_pipeline_step
    from app.pipeline.stream import PipelineStream, StreamMode

    run_pipeline_step(
        PipelineStream(mode=StreamMode.SINGLE, r1=str(FIXTURE)),
        {"name": step, "params": params, "lanes": "R1"},
        outdir, "fastq", None, "airrprep",
    )


def main() -> None:
    if not FIXTURE.is_file():
        raise SystemExit(
            f"fixture missing: {FIXTURE}\\n"
            "Build it first with: run_component_matrix.py ClusterSets"
        )
    if not Path(USEARCH).is_file():
        raise SystemExit(
            f"USEARCH not found at {USEARCH}. USEARCH is proprietary and is "
            "not distributed with AIRRPrep; set USEARCH_BIN to your own "
            "licensed binary to run this test."
        )

    results = []
    for name, sub, extra, params in CASES:
        case_dir = WORK / name.replace(".", "_")
        native = run_native(sub, extra, case_dir / "native")
        airrprep = run_airrprep(name, params, case_dir / "airrprep")
        results.append({
            "operation": name,
            "denominator": "usearch-additional",
            "input": repo_relative(str(FIXTURE)),
            "parameters": params,
            "native": native,
            "airrprep": airrprep,
        })
        print(f"{name:22s} native: {native['outcome']:52s} "
              f"airrprep: {airrprep['outcome']}", flush=True)

    document = {
        "test": "USEARCH-specific ClusterSets test (additional; not part of "
                "the 47-case component matrix)",
        "usearch_version": "7.0.1090",
        "usearch_binary": Path(USEARCH).name,
        "platform": sys.platform,
        "input": repo_relative(str(FIXTURE)),
        "results": results,
    }
    (HERE / "usearch_clustersets.json").write_text(
        json.dumps(document, indent=2), encoding="utf-8"
    )
    with (HERE / "usearch_clustersets.tsv").open("w", encoding="utf-8") as fh:
        fh.write("\t".join([
            "operation", "denominator", "input", "parameters",
            "native_command", "native_status", "native_usearch_message",
            "airrprep_command", "airrprep_status", "airrprep_usearch_message",
        ]) + "\n")
        for r in results:
            fh.write("\t".join([
                r["operation"], r["denominator"], r["input"],
                json.dumps(r["parameters"], sort_keys=True),
                r["native"]["command"], r["native"]["outcome"],
                r["native"]["usearch_message"],
                r["airrprep"]["command"], r["airrprep"]["outcome"],
                r["airrprep"]["usearch_message"],
            ]) + "\n")
    print("\nwrote usearch_clustersets.json / .tsv")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--single-step":
        single_step(sys.argv[2], json.loads(sys.argv[3]), Path(sys.argv[4]))
    else:
        main()
