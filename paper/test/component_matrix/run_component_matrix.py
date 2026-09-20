# -*- coding: utf-8 -*-
"""
Per-operation test matrix: every one of the 47 bulk operations AIRRPrep
exposes, run through AIRRPrep's own step executor and as the equivalent native
pRESTO command on the same input, with the outputs compared.

    cd paper/test/component_matrix
    ../../../presto-backend/venv/Scripts/python.exe run_component_matrix.py

Options: --reuse keeps the fixtures of an earlier run, --merge keeps the results
of cases this run does not execute, and a bare name or --skip=NAME selects or
leaves out cases by prefix. The five cases that need an external tool pRESTO
drives through an open temporary file (the three ClusterSets operations, and
reference-guided assembly, which builds a BLAST database) cannot run on Windows
at all and are run in the Linux container instead -- see cluster-test/.

AIRRPrep side: app.pipeline.executor.run_pipeline_step, the function a job
calls for each step, with the parameters the web interface sends.
Native side: the pRESTO console script (FilterSeq.py, MaskPrimers.py, ...)
with the equivalent command-line options.

Inputs are the first 8,000 read pairs of SRR1383456 (UMI-barcoded 5' RACE,
MiSeq 2x250, Stern et al. 2014) and intermediates derived from them with
native pRESTO, so no AIRRPrep output ever feeds a test. ConvertHeaders cases
use 500 of these reads with headers rewritten into each vendor format.

Comparators (per case):
  records    identical record sets: identifier, sequence, quality and the
             annotation field/value set, record order ignored; pass and fail
             outputs compared separately where both sides write them
  parts      a fan-out: every native output file must equal exactly one
             AIRRPrep output file under the `records` comparison
  tables     tab-delimited outputs, matched by file-name keyword, compared
             as sets of rows keyed by column name
  sample     random sampling (no seed in pRESTO): equal sizes, no duplicate,
             every sampled record identical to an input record
  cluster    records identical apart from the cluster label, and the
             partition of records into clusters identical

Writes component_matrix.json and component_matrix.tsv.
"""

import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent.parent
BACKEND = REPO / "presto-backend"
VENV = BACKEND / "venv" / "Scripts"
# The three ClusterSets cases cannot run on Windows (pRESTO hands vsearch an
# open temporary file, which Windows locks), so they are run in the Linux
# container built by cluster-test/Dockerfile; there the interpreter, the pRESTO
# console scripts and vsearch come from the image instead of the venv.
PY = Path(os.environ.get("MATRIX_PYTHON") or VENV / "python.exe")
SCRIPTS = Path(os.environ.get("MATRIX_SCRIPTS") or VENV)
BENCH_INPUTS = BACKEND / "temp" / "bench" / "inputs"
WORK = HERE / "work"
N_PAIRS = 8000
SMALL_PAIRS = 300  # reference-guided assembly calls BLAST once per pair

TOOLS = {
    "muscle": Path(os.environ.get("MUSCLE_BIN") or r"C:\Tools\muscle\muscle3.8.31_i86win32.exe"),
    "usearch": Path(os.environ.get("USEARCH_BIN") or r"C:\Tools\usearch\usearch7.0.1090_win64.exe"),
    "vsearch": Path(os.environ.get("VSEARCH_BIN") or r"C:\Tools\vsearch\vsearch-2.31.0-win-x86_64\bin\vsearch.exe"),
    "blastn": Path(shutil.which("blastn") or "blastn"),
    "makeblastdb": Path(shutil.which("makeblastdb") or "makeblastdb"),
}

os.environ.setdefault("MUSCLE_BIN", str(TOOLS["muscle"]))
os.environ.setdefault("USEARCH_BIN", str(TOOLS["usearch"]))
os.environ.setdefault("VSEARCH_BIN", str(TOOLS["vsearch"]))
# Reference-guided assembly resolves its aligner from configuration, never
# from a step parameter (app/config.py), so the fixture paths are supplied
# the same way an operator would supply them.
os.environ.setdefault("BLASTN_BIN", str(TOOLS["blastn"]))
os.environ.setdefault("MAKEBLASTDB_BIN", str(TOOLS["makeblastdb"]))
os.environ.setdefault("WORKER_CPUS", "4")
sys.path.insert(0, str(BACKEND))

from app.core.file_store import save_file  # noqa: E402
from app.pipeline.executor import run_pipeline_step  # noqa: E402
from app.pipeline.stream import PipelineStream, StreamMode  # noqa: E402

#: AIRRPrep resolves a companion-file parameter (primer FASTA, reference,
#: offset table) through the upload store, so the fixtures are registered
#: there and the parameter carries the upload id, exactly as in a real job.
_uploads: dict[str, str] = {}


def upload_id(path: Path) -> str:
    key = str(path)
    if key not in _uploads:
        _uploads[key] = save_file(path, path.name, session_id="component-matrix")
    return _uploads[key]


# --------------------------------------------------------------------------
# parsing and comparison
# --------------------------------------------------------------------------

def parse_header(header: str) -> tuple[str, frozenset]:
    fields = header.split("|")
    ann = []
    for f in fields[1:]:
        if "=" in f:
            k, v = f.split("=", 1)
            ann.append((k, v))
    return fields[0], frozenset(ann)


def read_seq_file(path: Path) -> list[tuple]:
    text = path.read_text().splitlines()
    out = []
    if path.suffix.lower() in (".fastq", ".fq"):
        for i in range(0, len(text) - 3, 4):
            rid, ann = parse_header(text[i][1:].rstrip())
            out.append((rid, text[i + 1].strip(), text[i + 3].strip(), ann))
    else:
        rid, ann, seq = None, None, []
        for line in text:
            if line.startswith(">"):
                if rid is not None:
                    out.append((rid, "".join(seq), None, ann))
                rid, ann = parse_header(line[1:].rstrip())
                seq = []
            elif line.strip():
                seq.append(line.strip())
        if rid is not None:
            out.append((rid, "".join(seq), None, ann))
    return out


def compare_records(a: list[tuple], b: list[tuple]) -> dict:
    ca, cb = Counter(a), Counter(b)
    ids_a, ids_b = {r[0] for r in a}, {r[0] for r in b}
    return {
        "native_records": len(a),
        "airrprep_records": len(b),
        "identical": sum((ca & cb).values()),
        "only_native": sum((ca - cb).values()),
        "only_airrprep": sum((cb - ca).values()),
        "ids_only_native": len(ids_a - ids_b),
        "ids_only_airrprep": len(ids_b - ids_a),
        "ok": ca == cb,
    }


def read_table(path: Path) -> tuple[tuple, Counter]:
    lines = [l for l in path.read_text().splitlines() if l.strip()]
    if not lines:
        return (), Counter()
    cols = tuple(lines[0].split("\t"))
    rows = Counter(
        tuple(sorted(zip(cols, line.split("\t")))) for line in lines[1:]
    )
    return tuple(sorted(cols)), rows


SEQ_SUFFIXES = (".fastq", ".fasta", ".fq", ".fa")
TABLE_SUFFIXES = (".tab", ".tsv")


def seq_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.suffix.lower() in SEQ_SUFFIXES)


def table_files(directory: Path) -> list[Path]:
    return sorted(p for p in directory.rglob("*") if p.suffix.lower() in TABLE_SUFFIXES)


def is_fail(p: Path) -> bool:
    return "fail" in p.stem.lower()


# --------------------------------------------------------------------------
# running both sides
# --------------------------------------------------------------------------

_help_cache: dict = {}


def cli_supports(tool: str, sub: str | None, flag: str) -> bool:
    key = (tool, sub)
    if key not in _help_cache:
        args = [str(PY), str(SCRIPTS / tool)] + ([sub] if sub else []) + ["--help"]
        _help_cache[key] = subprocess.run(args, capture_output=True, text=True).stdout
    return re.search(rf"(^|\s){re.escape(flag)}(\s|$)", _help_cache[key], re.M) is not None


def repo_relative(text: str) -> str:
    """Paths in the released report are repo-relative and POSIX-separated,
    so the same report reads the same whichever host produced it."""
    trimmed = text.replace(str(REPO) + os.sep, "").replace(str(REPO), ".")
    return trimmed.replace("\\", "/") if os.sep == "\\" else trimmed


def run_native(tool: str, sub: str | None, args: list[str], outdir: Path, extra_flags=(), outname="native") -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    cmd = [str(PY), str(SCRIPTS / tool)] + ([sub] if sub else []) + [str(a) for a in args]
    if cli_supports(tool, sub, "--outdir"):
        cmd += ["--outdir", str(outdir)]
    if outname and cli_supports(tool, sub, "--outname"):
        cmd += ["--outname", outname]
    if cli_supports(tool, sub, "--nproc"):
        cmd += ["--nproc", "1"]
    for flag in extra_flags:
        if cli_supports(tool, sub, flag):
            cmd.append(flag)
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(outdir))
    return {
        "command": repo_relative(
            " ".join(Path(c).name if i < 2 else c for i, c in enumerate(cmd))
        ),
        "returncode": p.returncode,
        "seconds": round(time.time() - t0, 2),
        "stderr_tail": (p.stderr or "")[-600:],
    }


def run_airrprep(step: str, params: dict, inputs: list[Path], lanes: str, outdir: Path) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    file_type = "fastq" if inputs[0].suffix.lower() in (".fastq", ".fq") else "fasta"
    if len(inputs) == 2:
        stream = PipelineStream(mode=StreamMode.DUAL, r1=str(inputs[0]), r2=str(inputs[1]))
    else:
        stream = PipelineStream(mode=StreamMode.SINGLE, r1=str(inputs[0]))
    t0 = time.time()
    try:
        _, by_lane, output_paths, parts = run_pipeline_step(
            stream,
            {"name": step, "params": params, "lanes": lanes},
            outdir,
            file_type,
            None,
            "airrprep",
        )
        return {
            "ok": True,
            "seconds": round(time.time() - t0, 2),
            "by_lane": by_lane,
            "command": airrprep_command(step, params, inputs, lanes),
        }
    except (Exception, SystemExit) as e:
        return {"ok": False, "seconds": round(time.time() - t0, 2),
                "command": airrprep_command(step, params, inputs, lanes),
                "error": f"{type(e).__name__}: {e}"[:600],
                "traceback": traceback.format_exc()[-1500:]}


def airrprep_command(step: str, params: dict, inputs: list[Path], lanes: str) -> str:
    """The AIRRPrep-side call, in the same reproducible form as the native one.

    AIRRPrep has no command line: a job calls run_pipeline_step once per step
    with the parameters the web interface sends. This renders exactly that
    call, so the two sides of a case can be read next to each other.
    """
    stream = (
        f"DUAL(r1={repo_relative(str(inputs[0]))}, r2={repo_relative(str(inputs[1]))})"
        if len(inputs) == 2
        else f"SINGLE(r1={repo_relative(str(inputs[0]))})"
    )
    rendered = json.dumps(params, sort_keys=True, default=str)
    return (
        f"run_pipeline_step({stream}, "
        f'{{"name": "{step}", "params": {rendered}, "lanes": "{lanes}"}})'
    )


def one_line(text: str) -> str:
    """Collapse a command to a single TSV cell."""
    return " ".join((text or "").split())


def output_digest(directory: Path) -> str:
    """One SHA-256 over every output file a side wrote.

    Name and content of each file, in sorted order, so the digest identifies
    the whole output set rather than one file of it. Recomputing it from the
    archived case directory is what makes a reported outcome checkable.
    """
    digest = hashlib.sha256()
    for path in sorted(q for q in directory.rglob("*") if q.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(b"\x00")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# --------------------------------------------------------------------------
# comparators
# --------------------------------------------------------------------------

def cmp_records(native_dir: Path, air_dir: Path, case: dict) -> dict:
    nat = [p for p in seq_files(native_dir) if p.parent == native_dir]
    air = [p for p in seq_files(air_dir) if p.parent == air_dir]
    out = {}
    for label, pick in (("pass", lambda p: not is_fail(p)), ("fail", is_fail)):
        n = [p for p in nat if pick(p)]
        a = [p for p in air if pick(p)]
        keep = case.get("native_keep")
        if keep and label == "pass":
            n = [p for p in n if re.search(keep, p.name)]
        if label == "fail" and (not n or not a):
            continue  # only one side writes failed records
        if label == "fail" and (len(n) > 1 or len(a) > 1):
            # AssemblePairs.py writes the mates of a failed pair to one file per
            # input file, AIRRPrep writes both to the step's single _fail file.
            # The layout differs, the failed records must not: compare them as
            # one pool per side and keep the file names in the report.
            out[label] = {
                "native_files": [p.name for p in n],
                "airrprep_files": [p.name for p in a],
                **compare_records([r for p in n for r in read_seq_file(p)],
                                  [r for p in a for r in read_seq_file(p)]),
            }
            continue
        if len(n) != 1 or len(a) != 1:
            out[label] = {"ok": False, "error": f"expected one file each, got native {[p.name for p in n]}, airrprep {[p.name for p in a]}"}
            continue
        out[label] = compare_records(read_seq_file(n[0]), read_seq_file(a[0]))
    out["ok"] = bool(out) and all(v.get("ok") for v in out.values() if isinstance(v, dict))
    return out


def cmp_parts(native_dir: Path, air_dir: Path, case: dict) -> dict:
    nat = [p for p in seq_files(native_dir) if not is_fail(p)]
    air = [p for p in seq_files(air_dir) if not is_fail(p)]
    air_sets = {p: Counter(read_seq_file(p)) for p in air}
    matched, unmatched = 0, []
    for p in nat:
        c = Counter(read_seq_file(p))
        hit = next((q for q, s in air_sets.items() if s == c), None)
        if hit is None:
            unmatched.append(p.name)
        else:
            matched += 1
            del air_sets[hit]
    return {"native_parts": len(nat), "airrprep_parts": len(air), "matched_parts": matched,
            "unmatched_native": unmatched[:5], "unmatched_airrprep": [p.name for p in air_sets][:5],
            "records_in_parts": sum(len(read_seq_file(p)) for p in nat),
            "ok": matched == len(nat) == len(air) and len(nat) > 0}


TABLE_KEYS = ("position", "quality", "nucleotide", "set", "threshold", "headers", "table", "offset")


def cmp_tables(native_dir: Path, air_dir: Path, case: dict) -> dict:
    nat, air = table_files(native_dir), table_files(air_dir)
    results, ok = {}, bool(nat)
    for p in nat:
        # Both sides name a table <outname>_<descriptor>.tab ("error-set",
        # "distance-barcode", ...), so the descriptor is what identifies the
        # pair; the keyword list is the fallback for the tools whose two sides
        # name the table differently.
        descriptor = p.stem.split("_", 1)[1].lower() if "_" in p.stem else ""
        key = next((k for k in TABLE_KEYS if k in p.stem.lower()), None)
        cands = ([q for q in air if descriptor and q.stem.lower().endswith(descriptor)]
                 or [q for q in air if key and key in q.stem.lower()]
                 or (air if len(air) == 1 == len(nat) else []))
        if len(cands) != 1:
            results[p.name] = {"ok": False, "error": f"no unique AIRRPrep table for '{key}': {[q.name for q in air]}"}
            ok = False
            continue
        cn, rn = read_table(p)
        ca, ra = read_table(cands[0])
        same = cn == ca and rn == ra
        results[p.name] = {"airrprep_file": cands[0].name, "rows_native": sum(rn.values()),
                           "rows_airrprep": sum(ra.values()), "same_columns": cn == ca,
                           "identical_rows": sum((rn & ra).values()), "ok": same}
        ok &= same
    return {"tables": results, "ok": ok}


def cmp_sample(native_dir: Path, air_dir: Path, case: dict) -> dict:
    source = Counter()
    for f in case["inputs"]:
        source.update(read_seq_file(f))
    out, ok = {}, True
    for side, d in (("native", native_dir), ("airrprep", air_dir)):
        files = [p for p in seq_files(d) if not is_fail(p)]
        recs = [r for p in files for r in read_seq_file(p)]
        c = Counter(recs)
        out[side] = {"files": len(files), "records": len(recs),
                     "duplicates": sum(v - 1 for v in c.values() if v > 1),
                     "not_in_input": sum((c - source).values())}
    ok = (out["native"]["records"] == out["airrprep"]["records"] > 0
          and out["native"]["files"] == out["airrprep"]["files"]
          and out["native"]["not_in_input"] == out["airrprep"]["not_in_input"] == 0
          and out["native"]["duplicates"] == out["airrprep"]["duplicates"] == 0)
    out["ok"] = ok
    return out


def cmp_cluster(native_dir: Path, air_dir: Path, case: dict) -> dict:
    field = case.get("cluster_field", "CLUSTER")
    group = case.get("group_field")
    nat = [p for p in seq_files(native_dir) if not is_fail(p)]
    air = [p for p in seq_files(air_dir) if not is_fail(p)]
    if len(nat) != 1 or len(air) != 1:
        return {"ok": False, "error": f"files native {[p.name for p in nat]} airrprep {[p.name for p in air]}"}
    a, b = read_seq_file(nat[0]), read_seq_file(air[0])

    def strip(recs):
        return Counter((r[0], r[1], r[2], frozenset(kv for kv in r[3] if kv[0] != field)) for r in recs)

    def partition(recs):
        clusters = {}
        for r in recs:
            ann = dict(r[3])
            key = (ann.get(group) if group else None, ann.get(field))
            clusters.setdefault(key, set()).add(r[0])
        return {frozenset(v) for v in clusters.values()}

    exact = compare_records(a, b)
    same_records = strip(a) == strip(b)
    same_partition = partition(a) == partition(b)
    return {"exact": exact, "records_identical_except_label": same_records,
            "same_partition": same_partition,
            "clusters_native": len(partition(a)), "clusters_airrprep": len(partition(b)),
            "ok": same_records and same_partition}


COMPARATORS = {"records": cmp_records, "parts": cmp_parts, "tables": cmp_tables,
               "sample": cmp_sample, "cluster": cmp_cluster}


# --------------------------------------------------------------------------
# fixtures (all produced by native pRESTO)
# --------------------------------------------------------------------------

def head_fastq(src: Path, dst: Path, n: int) -> Path:
    with src.open() as fin, dst.open("w") as fout:
        for i, line in enumerate(fin):
            if i >= 4 * n:
                break
            fout.write(line)
    return dst


def native_fixture(tool, sub, args, outdir: Path, pattern: str, outname: str) -> Path:
    r = run_native(tool, sub, args, outdir, outname=outname)
    hits = sorted(outdir.glob(pattern))
    if r["returncode"] != 0 or len(hits) != 1:
        raise RuntimeError(f"fixture {tool} {sub} failed: {r} {[h.name for h in hits]}")
    return hits[0]


def build_fixtures(reuse: bool = False) -> dict:
    fx = WORK / "fixtures"
    cache = fx / "_fixtures.json"
    if reuse and cache.is_file():
        # Paths are stored relative to the repository root so that a cache built
        # on the host is also valid inside the container, where the repository
        # is mounted somewhere else (older caches held absolute paths).
        return {k: (Path(v) if Path(v).is_absolute() else REPO / v)
                for k, v in json.loads(cache.read_text()).items()}
    if fx.exists():
        shutil.rmtree(fx)
    fx.mkdir(parents=True)
    F = {}
    F["cprimers"] = BENCH_INPUTS / "Stern2014_CPrimers.fasta"
    F["vprimers"] = BENCH_INPUTS / "Stern2014_VPrimers.fasta"
    F["ref"] = BENCH_INPUTS / "IMGT_Human_IG_V.fasta"
    F["r1"] = head_fastq(BENCH_INPUTS / "SRR1383456_1.fastq", fx / "raw_R1.fastq", N_PAIRS)
    F["r2"] = head_fastq(BENCH_INPUTS / "SRR1383456_2.fastq", fx / "raw_R2.fastq", N_PAIRS)
    F["r1p"] = native_fixture("MaskPrimers.py", "score", ["-s", F["r1"], "-p", F["cprimers"], "--start", 15, "--mode", "cut", "--barcode"], fx / "r1p", "*primers-pass.fastq", "R1")
    F["r2p"] = native_fixture("MaskPrimers.py", "score", ["-s", F["r2"], "-p", F["vprimers"], "--start", 0, "--mode", "mask"], fx / "r2p", "*primers-pass.fastq", "R2")
    d = fx / "pair"
    run_native("PairSeq.py", None, ["-1", F["r1p"], "-2", F["r2p"], "--1f", "BARCODE", "--coord", "sra"], d, outname=None)
    F["r1pair"] = next(d.glob("R1*pair-pass.fastq"))
    F["r2pair"] = next(d.glob("R2*pair-pass.fastq"))
    F["r1cons"] = native_fixture("BuildConsensus.py", None, ["-s", F["r1pair"], "--bf", "BARCODE", "--pf", "PRIMER", "--prcons", 0.6, "--maxerror", 0.1, "--maxgap", 0.5], fx / "r1cons", "*consensus-pass.fastq", "R1")
    F["r2cons"] = native_fixture("BuildConsensus.py", None, ["-s", F["r2pair"], "--bf", "BARCODE", "--maxerror", 0.1, "--maxgap", 0.5], fx / "r2cons", "*consensus-pass.fastq", "R2")
    d = fx / "conspair"
    run_native("PairSeq.py", None, ["-1", F["r1cons"], "-2", F["r2cons"], "--coord", "presto"], d, outname=None)
    F["r1cp"] = next(d.glob("R1*pair-pass.fastq"))
    F["r2cp"] = next(d.glob("R2*pair-pass.fastq"))
    F["r1cp_small"] = head_fastq(F["r1cp"], fx / "cons_small_R1.fastq", SMALL_PAIRS)
    F["r2cp_small"] = head_fastq(F["r2cp"], fx / "cons_small_R2.fastq", SMALL_PAIRS)
    F["asm"] = native_fixture("AssemblePairs.py", "align", ["-1", F["r2cp"], "-2", F["r1cp"], "--coord", "presto", "--rc", "tail", "--1f", "CONSCOUNT", "--2f", "CONSCOUNT", "PRCONS"], fx / "asm", "*assemble-pass.fastq", "ASM")
    F["asm_min"] = native_fixture("ParseHeaders.py", "collapse", ["-s", F["asm"], "-f", "CONSCOUNT", "--act", "min"], fx / "asm_min", "*reheader.fastq", "ASMMIN")
    F["offsets"] = native_fixture("AlignSets.py", "table", ["-p", F["cprimers"], "--exec", TOOLS["muscle"]], fx / "offsets", "*.tab", "OFFSETS")
    F.update(vendor_headers(F["r1"], fx / "vendor"))
    (fx / "_fixtures.json").write_text(json.dumps(
        {k: Path(v).resolve().relative_to(REPO).as_posix() for k, v in F.items()}, indent=1))
    return F


def vendor_headers(src: Path, d: Path) -> dict:
    d.mkdir(parents=True, exist_ok=True)
    recs = []
    with src.open() as fh:
        for i in range(500):
            h, s, _, q = (fh.readline().rstrip("\n") for _ in range(4))
            recs.append((s, q))
    bases = "ACGT"

    def umi(i):
        return "".join(bases[(i >> (2 * k)) & 3] for k in range(12))

    def write(name, fastq, header_fn):
        path = d / f"{name}.{'fastq' if fastq else 'fasta'}"
        with path.open("w") as out:
            for i, (s, q) in enumerate(recs):
                h = header_fn(i, s)
                out.write(f"@{h}\n{s}\n+\n{q}\n" if fastq else f">{h}\n{s}\n")
        return path

    return {
        "h454": write("h454", True, lambda i, s: f"GXGJ56Z01A{i:04d} length={len(s)}"),
        "hgenbank": write("hgenbank", False, lambda i, s: f"gi|5683{i:05d}|gb|MK{i:06d}.1| Homo sapiens IGH mRNA, partial cds"),
        "hgeneric": write("hgeneric", True, lambda i, s: f"read{i} sample=S1 lane:1"),
        "hillumina": write("hillumina", True, lambda i, s: f"MISEQ:132:000000000-A2F3U:1:1101:{14340 + i}:{1555 + i} 1:N:0:ATCACG"),
        "himgt": write("himgt", False, lambda i, s: f"X{60000 + i}|IGHV1-{i % 9 + 1}*0{i % 3 + 1}|Homo sapiens|F|V-REGION|142..417|{len(s)} nt|1| | | | |{len(s)}+24=300|partial in 3'| |"),
        "hmigec": write("hmigec", True, lambda i, s: f"MIG UMI:{umi(i)}:{i % 20 + 1}"),
        "hsra": src,
    }


# --------------------------------------------------------------------------
# the 47 operations
# --------------------------------------------------------------------------

def cases(F: dict) -> list[dict]:
    C = []

    def add(op, tool, sub, inputs, lanes, params, cli, kind="records",
            denominator="component-matrix-47", **extra):
        C.append(dict(op=op, tool=tool, sub=sub, inputs=inputs, lanes=lanes, params=params,
                      cli=cli, kind=kind, denominator=denominator, **extra))

    r1 = [F["r1"]]
    fs = ("--failed",)
    add("FilterSeq.length", "FilterSeq.py", "length", r1, "R1", {"min_length": 200, "inner": True}, ["-s", F["r1"], "-n", 200, "--inner"], native_flags=fs)
    add("FilterSeq.quality", "FilterSeq.py", "quality", r1, "R1", {"min_qual": 20, "inner": True}, ["-s", F["r1"], "-q", 20, "--inner"], native_flags=fs)
    add("FilterSeq.missing", "FilterSeq.py", "missing", r1, "R1", {"max_missing": 1, "inner": True}, ["-s", F["r1"], "-n", 1, "--inner"], native_flags=fs)
    add("FilterSeq.repeats", "FilterSeq.py", "repeats", r1, "R1", {"max_repeat": 20, "include_missing": False, "inner": True}, ["-s", F["r1"], "-n", 20, "--inner"], native_flags=fs)
    add("FilterSeq.trimqual", "FilterSeq.py", "trimqual", r1, "R1", {"min_qual": 20, "window": 10, "reverse": False}, ["-s", F["r1"], "-q", 20, "--win", 10], native_flags=fs)
    add("FilterSeq.maskqual", "FilterSeq.py", "maskqual", r1, "R1", {"min_qual": 20}, ["-s", F["r1"], "-q", 20], native_flags=fs)

    add("MaskPrimers.align", "MaskPrimers.py", "align", r1, "R1",
        {"primer_file": upload_id(F["cprimers"]), "max_len": 50, "max_error": 0.2, "mode": "cut"},
        ["-s", F["r1"], "-p", F["cprimers"], "--maxlen", 50, "--maxerror", 0.2, "--mode", "cut"], native_flags=fs)
    add("MaskPrimers.score", "MaskPrimers.py", "score", r1, "R1",
        {"primer_file": upload_id(F["cprimers"]), "start": 15, "mode": "cut", "barcode": True},
        ["-s", F["r1"], "-p", F["cprimers"], "--start", 15, "--mode", "cut", "--barcode"], native_flags=fs)
    add("MaskPrimers.extract", "MaskPrimers.py", "extract", r1, "R1",
        {"length": 15, "start": 0, "mode": "cut", "barcode": True},
        ["-s", F["r1"], "--len", 15, "--start", 0, "--mode", "cut", "--barcode"], native_flags=fs)

    add("CollapseSeq.default", "CollapseSeq.py", None, [F["asm_min"]], "R1",
        {"max_missing": 20, "inner": True, "uniq_fields": ["PRCONS"], "copy_fields": ["CONSCOUNT"], "copy_actions": ["sum"]},
        ["-s", F["asm_min"], "-n", 20, "--inner", "--uf", "PRCONS", "--cf", "CONSCOUNT", "--act", "sum"],
        native_keep=r"collapse-unique")
    add("BuildConsensus.default", "BuildConsensus.py", None, [F["r1pair"]], "R1",
        {"barcode_field": "BARCODE", "primer_field": "PRIMER", "primer_freq": 0.6, "max_error": 0.1, "max_gap": 0.5},
        ["-s", F["r1pair"], "--bf", "BARCODE", "--pf", "PRIMER", "--prcons", 0.6, "--maxerror", 0.1, "--maxgap", 0.5], native_flags=fs)
    add("PairSeq.default", "PairSeq.py", None, [F["r1p"], F["r2p"]], "paired",
        {"fields_1": ["BARCODE"], "coord_type": "sra"},
        ["-1", F["r1p"], "-2", F["r2p"], "--1f", "BARCODE", "--coord", "sra"], kind="parts", native_flags=fs)

    head_tail = {"swap_head_tail": True, "rc": "tail", "head_fields": ["CONSCOUNT"], "tail_fields": ["CONSCOUNT", "PRCONS"], "coord_type": "presto"}
    asm_cli = ["--coord", "presto", "--rc", "tail", "--1f", "CONSCOUNT", "--2f", "CONSCOUNT", "PRCONS"]
    add("AssemblePairs.align", "AssemblePairs.py", "align", [F["r1cp"], F["r2cp"]], "paired", dict(head_tail),
        ["-1", F["r2cp"], "-2", F["r1cp"], *asm_cli], native_flags=fs, airrprep_name="AssembleSeq.align")
    add("AssemblePairs.join", "AssemblePairs.py", "join", [F["r1cp"], F["r2cp"]], "paired", {**head_tail, "gap": 0},
        ["-1", F["r2cp"], "-2", F["r1cp"], *asm_cli, "--gap", 0], native_flags=fs, airrprep_name="AssembleSeq.join")
    ref = {"ref_file": upload_id(F["ref"]), "aligner": "blastn"}
    ref_cli = ["-r", F["ref"], "--aligner", "blastn", "--exec", TOOLS["blastn"], "--dbexec", TOOLS["makeblastdb"]]
    add("AssemblePairs.reference", "AssemblePairs.py", "reference", [F["r1cp_small"], F["r2cp_small"]], "paired", {**head_tail, **ref},
        ["-1", F["r2cp_small"], "-2", F["r1cp_small"], *asm_cli, *ref_cli], native_flags=fs, airrprep_name="AssembleSeq.reference")
    add("AssemblePairs.sequential", "AssemblePairs.py", "sequential", [F["r1cp_small"], F["r2cp_small"]], "paired", {**head_tail, **ref, "scan_reverse": True},
        ["-1", F["r2cp_small"], "-2", F["r1cp_small"], *asm_cli, *ref_cli, "--scanrev"], native_flags=fs, airrprep_name="AssembleSeq.sequential")

    asm = [F["asm"]]
    add("ParseHeaders.add", "ParseHeaders.py", "add", asm, "R1", {"fields": ["SAMPLE"], "values": ["S1"]}, ["-s", F["asm"], "-f", "SAMPLE", "-u", "S1"])
    add("ParseHeaders.collapse", "ParseHeaders.py", "collapse", asm, "R1", {"fields": ["CONSCOUNT"], "actions": ["min"]}, ["-s", F["asm"], "-f", "CONSCOUNT", "--act", "min"])
    add("ParseHeaders.copy", "ParseHeaders.py", "copy", asm, "R1", {"fields": ["PRCONS"], "names": ["ISOTYPE"]}, ["-s", F["asm"], "-f", "PRCONS", "-k", "ISOTYPE"])
    add("ParseHeaders.delete", "ParseHeaders.py", "delete", asm, "R1", {"fields": ["PRCONS"]}, ["-s", F["asm"], "-f", "PRCONS"])
    add("ParseHeaders.expand", "ParseHeaders.py", "expand", asm, "R1", {"fields": ["CONSCOUNT"], "separator": ","}, ["-s", F["asm"], "-f", "CONSCOUNT", "--sep", ","])
    add("ParseHeaders.merge", "ParseHeaders.py", "merge", asm, "R1", {"fields": ["CONSCOUNT", "PRCONS"], "name": "MERGED"}, ["-s", F["asm"], "-f", "CONSCOUNT", "PRCONS", "-k", "MERGED"])
    add("ParseHeaders.rename", "ParseHeaders.py", "rename", asm, "R1", {"fields": ["PRCONS"], "names": ["ISOTYPE"]}, ["-s", F["asm"], "-f", "PRCONS", "-k", "ISOTYPE"])
    add("ParseHeaders.table", "ParseHeaders.py", "table", asm, "R1", {"fields": ["ID", "PRCONS", "CONSCOUNT"]}, ["-s", F["asm"], "-f", "ID", "PRCONS", "CONSCOUNT"], kind="tables")

    amin = [F["asm_min"]]
    add("SplitSeq.count", "SplitSeq.py", "count", amin, "R1", {"max_count": 100}, ["-s", F["asm_min"], "-n", 100], kind="parts")
    add("SplitSeq.group", "SplitSeq.py", "group", amin, "R1", {"field": "PRCONS"}, ["-s", F["asm_min"], "-f", "PRCONS"], kind="parts")
    add("SplitSeq.sample", "SplitSeq.py", "sample", amin, "R1", {"max_count": [100]}, ["-s", F["asm_min"], "-n", 100], kind="sample")
    add("SplitSeq.samplepair", "SplitSeq.py", "samplepair", [F["r1cp"], F["r2cp"]], "paired", {"max_count": [100], "coord_type": "presto"},
        ["-1", F["r1cp"], "-2", F["r2cp"], "-n", 100, "--coord", "presto"], kind="sample")
    add("SplitSeq.sort", "SplitSeq.py", "sort", amin, "R1", {"field": "CONSCOUNT", "numeric": True}, ["-s", F["asm_min"], "-f", "CONSCOUNT", "--num"], kind="parts")
    add("SplitSeq.select", "SplitSeq.py", "select", amin, "R1", {"field": "PRCONS", "value_list": ["Human-IGHG"]}, ["-s", F["asm_min"], "-f", "PRCONS", "-u", "Human-IGHG"], kind="parts")

    r1p = [F["r1p"]]
    add("AlignSets.muscle", "AlignSets.py", "muscle", r1p, "R1", {"barcode_field": "BARCODE"}, ["-s", F["r1p"], "--bf", "BARCODE", "--exec", TOOLS["muscle"]], native_flags=fs)
    add("AlignSets.offset", "AlignSets.py", "offset", r1p, "R1", {"offset_file": upload_id(F["offsets"]), "barcode_field": "BARCODE", "primer_field": "PRIMER", "offset_mode": "pad"},
        ["-s", F["r1p"], "-d", F["offsets"], "--bf", "BARCODE", "--pf", "PRIMER", "--mode", "pad"], native_flags=fs)
    add("AlignSets.table", "AlignSets.py", "table", r1p, "R1", {"primer_file": upload_id(F["cprimers"])}, ["-p", F["cprimers"], "--exec", TOOLS["muscle"]], kind="tables")

    # The three ClusterSets operations are counted once each in the 47-case
    # matrix, with VSEARCH -- the open tool the container image carries and
    # the one a stock deployment uses. The same three run again against
    # USEARCH as a separate, additional test: USEARCH is proprietary, is not
    # redistributed, and is the tool for which pRESTO builds a command line
    # its own documented build rejects. Those three cases are therefore not
    # part of the 47-case denominator, and are labelled so in the report.
    for tool, denominator in (
        ("vsearch", "component-matrix-47"),
        ("usearch", "usearch-additional"),
    ):
        add(f"ClusterSets.all [{tool}]", "ClusterSets.py", "all", r1p, "R1", {"ident": 0.9, "cluster_tool": tool},
            ["-s", F["r1p"], "--ident", 0.9, "--cluster", tool, "--exec", TOOLS[tool]], kind="cluster", airrprep_name="ClusterSets.all", denominator=denominator)
        add(f"ClusterSets.barcode [{tool}]", "ClusterSets.py", "barcode", r1p, "R1", {"barcode_field": "BARCODE", "ident": 0.9, "cluster_tool": tool},
            ["-s", F["r1p"], "-f", "BARCODE", "--ident", 0.9, "--cluster", tool, "--exec", TOOLS[tool]], kind="cluster", airrprep_name="ClusterSets.barcode", denominator=denominator)
        add(f"ClusterSets.set [{tool}]", "ClusterSets.py", "set", r1p, "R1", {"set_field": "BARCODE", "ident": 0.9, "cluster_tool": tool},
            ["-s", F["r1p"], "-f", "BARCODE", "--ident", 0.9, "--cluster", tool, "--exec", TOOLS[tool]], kind="cluster", airrprep_name="ClusterSets.set", group_field="BARCODE", denominator=denominator)

    for vendor, key, extra_params, extra_cli in (
        ("454", "h454", {}, []), ("genbank", "hgenbank", {}, []), ("generic", "hgeneric", {}, []),
        ("illumina", "hillumina", {}, []), ("imgt", "himgt", {}, []), ("migec", "hmigec", {}, []), ("sra", "hsra", {}, []),
    ):
        add(f"ConvertHeaders.{vendor}", "ConvertHeaders.py", vendor, [F[key]], "R1", extra_params, ["-s", F[key], *extra_cli], native_flags=fs)

    add("EstimateError.barcode", "EstimateError.py", "barcode", r1p, "R1", {"barcode_field": "BARCODE"}, ["-s", F["r1p"], "-f", "BARCODE"], kind="tables")
    add("EstimateError.set", "EstimateError.py", "set", r1p, "R1", {"set_field": "BARCODE", "min_count": 3}, ["-s", F["r1p"], "-f", "BARCODE", "-n", 3], kind="tables")

    pair1 = [F["r1pair"]]
    add("UnifyHeaders.consensus", "UnifyHeaders.py", "consensus", pair1, "R1", {"set_field": "BARCODE", "unify_field": "PRIMER"}, ["-s", F["r1pair"], "-f", "BARCODE", "-k", "PRIMER"], native_flags=fs)
    add("UnifyHeaders.delete", "UnifyHeaders.py", "delete", pair1, "R1", {"set_field": "BARCODE", "unify_field": "PRIMER"}, ["-s", F["r1pair"], "-f", "BARCODE", "-k", "PRIMER"], native_flags=fs)
    return C


# --------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    reuse = "--reuse" in args
    merge = "--merge" in args
    #: names and --skip=NAME both match a case by prefix, so that a whole tool
    #: or one operation's tool variants can be selected or left out in one word
    skip = tuple(a.split("=", 1)[1] for a in args if a.startswith("--skip="))
    only = set(a for a in args if not a.startswith("--"))
    WORK.mkdir(parents=True, exist_ok=True)
    print("fixtures:", "reusing" if reuse else "building with native pRESTO ...", flush=True)
    F = build_fixtures(reuse=reuse)
    all_cases = cases(F)
    results = []
    for case in all_cases:
        paired_native = len(case["inputs"]) == 2 and case["tool"] in ("PairSeq.py", "SplitSeq.py")
        name = case["op"]
        if only and not any(name == o or name.startswith(o) for o in only):
            continue
        if any(name.startswith(s) for s in skip):
            continue
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")
        cdir = WORK / "cases" / slug
        if cdir.exists():
            shutil.rmtree(cdir)
        native = run_native(case["tool"], case["sub"], case["cli"], cdir / "native", case.get("native_flags", ()),
                            outname=None if paired_native else "native")
        air = run_airrprep(case.get("airrprep_name", name), case["params"], case["inputs"], case["lanes"], cdir / "airrprep")
        entry = {
            "operation": name,
            "denominator": case.get("denominator", "component-matrix-47"),
            "host": sys.platform,
            "comparator": case["kind"],
            "inputs": [repo_relative(str(q)) for q in case["inputs"]],
            "parameters": {k: v for k, v in sorted(case["params"].items())},
            "lanes": case["lanes"],
            "native": native,
            "airrprep": air,
        }
        if native["returncode"] != 0 or not air["ok"]:
            if native["returncode"] != 0 and air["ok"]:
                # Not a disagreement: there is no native output to compare
                # against, so the case is reported as not comparable.
                entry["outcome"] = "not comparable (native pRESTO failed)"
            elif native["returncode"] == 0 and not air["ok"]:
                entry["outcome"] = "AIRRPrep failed"
            else:
                entry["outcome"] = "both failed"
        else:
            try:
                comp = COMPARATORS[case["kind"]](cdir / "native", cdir / "airrprep", case)
            except Exception as e:
                comp = {"ok": False, "error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-1200:]}
            entry["comparison"] = comp
            entry["outcome"] = "identical" if comp.get("ok") else "DIFFERENT"
        entry["output_sha256"] = {
            "native": output_digest(cdir / "native"),
            "airrprep": output_digest(cdir / "airrprep"),
        }
        results.append(entry)
        print(f"{name:34s} {entry['outcome']:28s} native {native['seconds']}s / airrprep {air['seconds']}s", flush=True)
        if entry["outcome"] != "identical":
            if native["returncode"] != 0:
                print("    native:", native["stderr_tail"].replace(chr(10), " ")[-300:], flush=True)
            if not air["ok"]:
                print("    airrprep:", air.get("error", ""), flush=True)
            comp = entry.get("comparison") or {}
            if comp and not comp.get("ok"):
                print("    comparison:", json.dumps(comp, default=str)[:500], flush=True)

    out = HERE / "component_matrix.json"
    #: --merge keeps the results of cases this run did not execute, so the
    #: report can be completed by a second run elsewhere (the ClusterSets cases
    #: are run in the Linux container); the case order stays canonical.
    report = json.loads(out.read_text()) if merge and out.is_file() else {}
    inputs = report.get("inputs", {})
    inputs["source"] = "SRR1383456 first %d read pairs" % N_PAIRS
    #: keyed by platform, because a merged report has cases from both
    inputs.setdefault("tools", {})[sys.platform] = {
        "python": str(PY), "scripts": str(SCRIPTS),
        **{k: str(v) for k, v in TOOLS.items()},
    }
    by_name = {r["operation"]: r for r in report.get("results", [])}
    by_name.update({r["operation"]: r for r in results})
    order = [c["op"] for c in all_cases]
    results = [by_name[op] for op in order if op in by_name]

    #: A merged report mixes cases from this run with cases run elsewhere (the
    #: five that only run in the Linux container). The static fields of a case
    #: -- which denominator it belongs to, its inputs, its parameters, the
    #: AIRRPrep call -- come from the case definition, so they can be filled in
    #: for every case whatever ran it; the output digests are recomputed from
    #: that case's archived directory, which is released with the report.
    by_case = {c["op"]: c for c in all_cases}
    for entry in results:
        case = by_case.get(entry["operation"])
        if not case:
            continue
        # These are derived from the case definition, so they are rewritten
        # rather than filled in only when absent: a report merged from two
        # hosts must render paths and commands the same way on both sides.
        entry["denominator"] = case.get("denominator", "component-matrix-47")
        entry["inputs"] = [repo_relative(str(q)) for q in case["inputs"]]
        entry["parameters"] = {k: v for k, v in sorted(case["params"].items())}
        entry["lanes"] = case["lanes"]
        entry["airrprep"]["command"] = airrprep_command(
            case.get("airrprep_name", case["op"]), case["params"],
            case["inputs"], case["lanes"],
        )
        entry["native"]["command"] = repo_relative(entry["native"]["command"])
        # A case merged from the other host keeps the host it ran on. The
        # native command names the interpreter, and only Windows spells it
        # python.exe, so a report merged before this field existed can still
        # say where each case ran.
        if "host" not in entry:
            entry["host"] = ("win32" if "python.exe" in entry["native"]["command"]
                             else "linux")
        if "output_sha256" not in entry:
            cdir = WORK / "cases" / re.sub(r"[^A-Za-z0-9]+", "_", case["op"]).strip("_")
            if cdir.is_dir():
                entry["output_sha256"] = {
                    "native": output_digest(cdir / "native"),
                    "airrprep": output_digest(cdir / "airrprep"),
                }
    out.write_text(json.dumps({"inputs": inputs, "results": results},
                              indent=2, default=str))
    with (HERE / "component_matrix.tsv").open("w", newline="") as fh:
        w = csv.writer(fh, delimiter="\t")
        w.writerow([
            "operation", "denominator", "host", "input", "parameters",
            "native_command", "airrprep_command", "comparator", "status",
            "native_output_sha256", "airrprep_output_sha256",
        ])
        for r in results:
            digests = r.get("output_sha256", {})
            w.writerow([
                r["operation"],
                r.get("denominator", ""),
                r.get("host", ""),
                "; ".join(r.get("inputs", [])),
                json.dumps(r.get("parameters", {}), sort_keys=True, default=str),
                one_line(r["native"]["command"]),
                one_line(r["airrprep"].get("command", "")),
                r["comparator"],
                r["outcome"],
                digests.get("native", ""),
                digests.get("airrprep", ""),
            ])
    for denominator in sorted({r.get("denominator", "component-matrix-47")
                               for r in results}):
        subset = [r for r in results
                  if r.get("denominator", "component-matrix-47") == denominator]
        print(f"{denominator} ({len(subset)} cases):",
              dict(Counter(r["outcome"] for r in subset)))
    counts = Counter(r["outcome"] for r in results)
    print("\nSUMMARY:", dict(counts))


if __name__ == "__main__":
    main()
