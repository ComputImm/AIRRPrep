"""
Write paper/TEST_SUMMARY.json: which automated tests pass, and the counts
behind every headline number in the manuscript.

    cd paper
    ../presto-backend/venv/Scripts/python.exe make_test_summary.py

The backend suite is run here and its result recorded per test. The
validation and benchmark numbers are read from the reports those runs
produced, rather than restated, so this file cannot drift away from them: if
a report is missing, its entry says so instead of carrying a number.
"""

from __future__ import annotations

import json
import re
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BACKEND = REPO / "presto-backend"


def run_backend_suite() -> dict:
    """Run backend/tests exactly as the README says to, and record the result.

    A subprocess, not an in-process loader: the command recorded here is then
    literally the one a reader runs, and `tests/` needs the backend directory
    as the working directory to be importable at all.
    """
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    started = time.time()
    proc = subprocess.run(
        command, cwd=str(BACKEND), capture_output=True, text=True,
    )
    output = (proc.stdout or "") + (proc.stderr or "")

    # unittest -v prints "test_x (module.Class.test_x)" and then either
    # "... ok" on the same line or, when the test has a docstring, the
    # docstring and the status on the next line. Both forms are counted.
    by_module: Counter[str] = Counter()
    failures: list[str] = []
    per_test = 0
    pending: str | None = None
    status_only = re.compile(r"\.\.\. (ok|FAIL|ERROR|skipped.*|expected failure)\s*$")
    header = re.compile(r"^(\S+) \(([\w.]+)\)")

    for line in output.splitlines():
        match = header.match(line)
        if match:
            pending = match.group(2)
            parts = pending.split(".")
            by_module[".".join(parts[:2]) if len(parts) > 1 else pending] += 1
            per_test += 1
        found = status_only.search(line)
        if found and pending:
            if found.group(1) in ("FAIL", "ERROR"):
                failures.append(f"{pending}: {found.group(1)}")
            pending = None

    total = re.search(r"^Ran (\d+) tests? in ([\d.]+)s", output, re.M)
    return {
        "command": "cd presto-backend && python -m unittest discover -s tests",
        "run": int(total.group(1)) if total else per_test,
        "passed": (int(total.group(1)) if total else per_test) - len(failures),
        "failed": failures,
        "wall_seconds": round(time.time() - started, 2),
        "tests_per_module": dict(sorted(by_module.items())),
        "all_passed": proc.returncode == 0,
        "exit_code": proc.returncode,
    }


def load(path: Path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def component_matrix() -> dict:
    data = load(HERE / "test" / "component_matrix" / "component_matrix.json")
    if data is None:
        return {"available": False,
                "note": "component_matrix.json not present; run run_component_matrix.py"}
    results = data["results"]
    by_denominator: dict[str, Counter] = {}
    for row in results:
        key = row.get("denominator", "component-matrix-47")
        by_denominator.setdefault(key, Counter())[row["outcome"]] += 1
    return {
        "available": True,
        "cases": len(results),
        "by_denominator": {k: dict(v) for k, v in sorted(by_denominator.items())},
        "not_comparable": [r["operation"] for r in results
                           if r["outcome"] != "identical"],
        "every_case_has_an_output_digest": all(
            "output_sha256" in r for r in results),
    }


def usearch_test() -> dict:
    data = load(HERE / "test" / "component_matrix" / "usearch_clustersets.json")
    if data is None:
        return {"available": False,
                "note": "usearch_clustersets.json not present; needs a USEARCH licence"}
    return {
        "available": True,
        "separate_from_the_47": True,
        "usearch_version": data.get("usearch_version"),
        "platform": data.get("platform"),
        "cases": [
            {"operation": r["operation"],
             "native": r["native"]["outcome"],
             "airrprep": r["airrprep"]["outcome"]}
            for r in data["results"]
        ],
    }


def singlecell() -> dict:
    data = load(HERE / "test" / "validation_report.json")
    if data is None:
        return {"available": False,
                "note": "validation_report.json not present; run validate_singlecell.py"}
    cases = []
    for row in data:
        join = row.get("source_annotations") or {}
        cases.append({
            "case": row["case"],
            "source_records": row.get("source_records"),
            "output_records": row.get("output_records"),
            "discrepancies": row.get("discrepancies", []),
            "source_annotation_rows": join.get("rows"),
            "source_annotation_columns_preserved": join.get("source_columns_preserved"),
            "rows_that_do_not_join_back": (
                None if not join.get("written") else
                join["duplicate_ids"]
                + join["rows_without_a_normalized_record"]
                + join["normalized_records_without_a_row"]
            ),
        })
    return {
        "available": True,
        "cases": cases,
        "all_clean": all(not c["discrepancies"] for c in cases),
    }


def trust4() -> dict:
    data = load(HERE / "test" / "trust4_validation" / "trust4_validation.json")
    if data is None:
        return {"available": False,
                "note": "trust4_validation.json not present; run validate_trust4.py"}
    return {"available": True, "raw": data if len(json.dumps(data)) < 20000 else "see file"}


def benchmark() -> dict:
    data = load(BACKEND / "temp" / "bench" / "results.json")
    if data is None:
        return {"available": False,
                "note": "results.json not present; run benchmark.py"}
    return {
        "available": True,
        "scope": "one Windows 11 workstation, 25,000-read-pair subsets; "
                 "small-input execution overhead, not production throughput",
        "keys": sorted(data)[:20] if isinstance(data, dict) else f"{len(data)} entries",
    }


def main() -> int:
    summary = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "host": {
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "backend_test_suite": run_backend_suite(),
        "component_matrix": component_matrix(),
        "usearch_clustersets_test": usearch_test(),
        "singlecell_validation": singlecell(),
        "trust4_validation": trust4(),
        "benchmark": benchmark(),
    }
    out = HERE / "TEST_SUMMARY.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    suite = summary["backend_test_suite"]
    print(f"backend suite      {suite['passed']}/{suite['run']} passed "
          f"in {suite['wall_seconds']}s")
    matrix = summary["component_matrix"]
    if matrix["available"]:
        for key, counts in matrix["by_denominator"].items():
            print(f"{key:24s} {counts}")
    single = summary["singlecell_validation"]
    if single["available"]:
        print(f"single-cell        {'clean' if single['all_clean'] else 'DISCREPANCIES'}")
    print(f"wrote {out}")
    return 0 if suite["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
