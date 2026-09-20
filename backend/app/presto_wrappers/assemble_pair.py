# app/presto_wrappers/assemble_pair.py
"""
Four independent AssembleSeq wrappers (align / join / reference / sequential).
Each public function is self-contained — same style as MaskPrimers / ParseHeaders.
"""

from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from itertools import islice
from pathlib import Path

from Bio import SeqIO

from app.config import (
    ALIGNER_BINS,
    ALIGNER_DB_BINS,
    DEFAULT_REFERENCE_ALIGNER,
    EXTERNAL_TOOL_CPUS,
)
from app.core.file_store import get_file
from app.presto_wrappers.align_sets import require_executable
from presto.Applications import makeBlastnDb, makeUBlastDb
from presto.Annotation import (
    flattenAnnotation,
    getCoordKey,
    mergeAnnotation,
    parseAnnotation,
)
from presto.Defaults import (
    default_assembly_alpha,
    default_assembly_evalue,
    default_assembly_gap,
    default_assembly_max_error,
    default_assembly_max_hits,
    default_assembly_max_len,
    default_assembly_min_ident,
    default_assembly_min_len,
    default_coord,
    default_delimiter,
)
from presto.IO import readReferenceFile
from presto.Sequence import (
    AssemblyStats,
    alignAssembly,
    joinAssembly,
    referenceAssembly,
    reverseComplement,
    sequentialAssembly,
)


def assemble_output_paths(output_file: str):
    path = Path(output_file)
    return str(path), str(path.with_name(f"{path.stem}_fail{path.suffix}"))


def _resolve_ref_path(ref_file: str) -> str:
    stored = get_file(ref_file)
    if not stored:
        raise ValueError(f"Reference file not found: {ref_file}")
    return stored.path


def _open_reference_db(ref_path: str, aligner: str):
    """Build ref_dict + ref_db for referenceAssembly / sequentialAssembly only.

    Returns the resolved aligner executable alongside them. Both binaries come
    from app.config, never from step parameters: pRESTO's ``--exec`` is a
    local-CLI convenience, but on a hosted service a request that names the
    executable chooses which binary the worker runs.

    The default aligner is blastn, which the container image carries. USEARCH
    (ublast) remains selectable, but it is proprietary and not redistributed,
    so it only works where the operator has installed it and set USEARCH_BIN.
    """
    aligner = (aligner or DEFAULT_REFERENCE_ALIGNER).lower()
    if aligner not in ALIGNER_BINS:
        raise ValueError(
            f"aligner must be one of {', '.join(sorted(ALIGNER_BINS))}"
        )
    aligner_exec = require_executable(
        ALIGNER_BINS[aligner], f"Reference-guided assembly ({aligner})"
    )
    db_exec = require_executable(
        ALIGNER_DB_BINS[aligner], f"Reference-guided assembly ({aligner})"
    )

    ref_dict = readReferenceFile(ref_path)
    db_func = {"blastn": makeBlastnDb, "usearch": makeUBlastDb}[aligner]
    ref_db, db_handle = db_func(ref_path, db_exec)

    return ref_dict, ref_db, db_handle, aligner, aligner_exec


def _close_db(db_handle):
    if db_handle is None:
        return
    try:
        db_handle.close()
    except AttributeError:
        db_handle.cleanup()


def _pair_coordinate(head_record, tail_record, coord_type, delimiter):
    """
    The coordinate the two mates share, or None when they do not belong together.

    AssemblePairs.py is told which header format it is reading (--coord) and
    raises when the two keys disagree. AIRRPrep is not told: the workflow editor
    has no coordinate-type control, and its input is whatever was uploaded. Raw
    SRA/ENA reads carry a per-mate description ("ERR346600.1 1 length=250"),
    whose presto key -- the whole field -- differs between mates that do belong
    together, which is why the command-line reference workflow for that dataset
    passes --coord sra.

    So the configured type is tried first and the Illumina rule (leading
    identifier, mate suffix and index removed) second; the second rule is what
    lets raw paired reads assemble, under the same identifiers the command line
    produces with --coord sra. Disagreeing under both means the two files have
    drifted out of sync (an asymmetric upstream filter, a re-ordered retry, ...),
    which has to fail loudly rather than stitch unrelated reads together: a bare
    zip() would do exactly that silently.
    """
    head_key = getCoordKey(
        head_record.description, coord_type=coord_type, delimiter=delimiter
    )
    tail_key = getCoordKey(
        tail_record.description, coord_type=coord_type, delimiter=delimiter
    )
    if head_key == tail_key:
        return head_key
    head_id = getCoordKey(
        head_record.description, coord_type="illumina", delimiter=delimiter
    )
    tail_id = getCoordKey(
        tail_record.description, coord_type="illumina", delimiter=delimiter
    )
    return head_id if head_id == tail_id else None


def _prepared_pairs(
    head_file, tail_file, file_type, rc, head_fields, tail_fields, delimiter,
    coord_type=default_coord,
):
    """
    Yield (head_record, tail_record, head_seq, tail_seq, stitch_ann) in file
    order: the records as they were read, which is what a failed pair is
    written back as, and the oriented copies the assembler works on.

    Everything here is ordering-sensitive and cheap, so it stays in the parent
    process; only the assembly call itself is worth handing to a pool.
    """
    for head_record, tail_record in zip(
        SeqIO.parse(head_file, file_type),
        SeqIO.parse(tail_file, file_type),
    ):
        coordinate = _pair_coordinate(
            head_record, tail_record, coord_type, delimiter
        )
        if coordinate is None:
            raise ValueError(
                f"Coordinates for sequences {head_record.description} and "
                f"{tail_record.description} do not match"
            )

        head_seq = (
            reverseComplement(head_record) if rc in ("head", "both") else head_record
        )
        tail_seq = (
            reverseComplement(tail_record) if rc in ("tail", "both") else tail_record
        )

        # The stitched record is named after the pair's coordinate, not after
        # the head record's own header: with the presto coordinate type that
        # header still carries the upstream annotations, and putting it in the
        # ID field would repeat them alongside the merged ones.
        stitch_ann = OrderedDict([("ID", coordinate)])
        if head_fields:
            stitch_ann = mergeAnnotation(
                stitch_ann,
                parseAnnotation(
                    head_seq.description, head_fields, delimiter=delimiter
                ),
                delimiter=delimiter,
            )
        if tail_fields:
            stitch_ann = mergeAnnotation(
                stitch_ann,
                parseAnnotation(
                    tail_seq.description, tail_fields, delimiter=delimiter
                ),
                delimiter=delimiter,
            )
        yield head_record, tail_record, head_seq, tail_seq, stitch_ann


# Rebuilt once per pool worker by _init_assembly_worker, rather than pickled
# with every record pair: the reference dictionary and the assembly statistics
# table are identical for the whole run and dwarf a pair of reads.
_ASSEMBLY_CTX = None


_ASSEMBLY_FUNCS = {
    "align": alignAssembly,
    "join": joinAssembly,
    "reference": referenceAssembly,
    "sequential": sequentialAssembly,
}

# Join width, kept separate from the other modes because the trade-off is not
# the same: joining a pair is one concatenation, which is less work than
# shipping the pair to another process and the result back. Measured on 8,000
# pairs (temp/bench/verify_join.py): 0.94 s serial against 5.61 s across eight
# workers -- same output, six times slower. So join runs serially, and this
# constant is the switch if that ever stops being true (a machine with cheap
# process startup, or much longer reads).
JOIN_CPUS = 1


def _init_assembly_worker(mode, ref_path, kwargs, stats_max_len):
    global _ASSEMBLY_CTX
    ctx = dict(kwargs)
    if ref_path is not None:
        ctx["ref_dict"] = readReferenceFile(ref_path)
    if stats_max_len is not None:
        ctx["assembly_stats"] = AssemblyStats(stats_max_len + 1)
    _ASSEMBLY_CTX = (mode, ctx)


def _assemble_one(pair):
    mode, ctx = _ASSEMBLY_CTX
    return _ASSEMBLY_FUNCS[mode](pair[0], pair[1], **ctx)


def _assembled(prepared, mode, ref_path, kwargs, stats_max_len, workers,
               batch_size=1000):
    """
    Assemble prepared pairs across `workers` processes, yielding in input order.

    Every mode benefits, for two different reasons. Reference-guided assembly
    launches an external aligner once per read pair -- blastn and ublast are
    both hard-coded to a single thread by pRESTO -- so running several of those
    processes at once is the only way to use more than one core. De novo align
    and join spawn nothing, but scoring an overlap is pure CPU work and scales
    the same way. Either way this is what the pRESTO command line does with
    --nproc; here the width comes from configuration.

    Pairs are pulled in bounded batches because ProcessPoolExecutor.map()
    consumes its whole input iterable up front, which for a large file would
    mean holding every read in memory at once.
    """
    kwargs = {
        k: v for k, v in kwargs.items() if k not in ("ref_dict", "assembly_stats")
    }

    if workers <= 1:
        _init_assembly_worker(mode, ref_path, kwargs, stats_max_len)
        for head_record, tail_record, head_seq, tail_seq, ann in prepared:
            yield head_record, tail_record, ann, _assemble_one((head_seq, tail_seq))
        return

    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_assembly_worker,
        initargs=(mode, ref_path, kwargs, stats_max_len),
    ) as pool:
        while True:
            batch = list(islice(prepared, batch_size))
            if not batch:
                break
            stitches = pool.map(
                _assemble_one,
                [(head, tail) for _, _, head, tail, _ in batch],
                chunksize=max(1, len(batch) // (workers * 4)),
            )
            for (head_record, tail_record, _h, _t, ann), stitch in zip(batch, stitches):
                yield head_record, tail_record, ann, stitch


def run_assemble_align(
    head_file,
    tail_file,
    output_file,
    file_type="fastq",
    rc="tail",
    head_fields=None,
    tail_fields=None,
    alpha=default_assembly_alpha,
    max_error=default_assembly_max_error,
    min_len=default_assembly_min_len,
    max_len=default_assembly_max_len,
    scan_reverse=False,
    coord_type=default_coord,
    delimiter=default_delimiter,
):
    """
    De novo overlap assembly (AssemblePairs.py align).
    No reference file.
    """
    output_pass, output_fail = assemble_output_paths(output_file)
    assemble_kwargs = {
        "alpha": alpha,
        "max_error": max_error,
        "min_len": min_len,
        "max_len": max_len,
        "scan_reverse": scan_reverse,
        "assembly_stats": AssemblyStats(max_len + 1),
    }

    pass_count = 0
    fail_count = 0

    prepared = _prepared_pairs(
        head_file, tail_file, file_type, rc, head_fields, tail_fields, delimiter,
        coord_type=coord_type,
    )

    with open(output_pass, "w") as pass_handle, open(output_fail, "w") as fail_handle:
        for head_record, tail_record, stitch_ann, stitch in _assembled(
            prepared, "align", None, assemble_kwargs, max_len, EXTERNAL_TOOL_CPUS
        ):
            if stitch.seq is not None and getattr(stitch, "valid", True):
                stitch.seq.id = flattenAnnotation(stitch_ann, delimiter=delimiter)
                stitch.seq.name = stitch.seq.id
                stitch.seq.description = ""
                SeqIO.write(stitch.seq, pass_handle, file_type)
                pass_count += 1
            else:
                SeqIO.write(head_record, fail_handle, file_type)
                SeqIO.write(tail_record, fail_handle, file_type)
                fail_count += 1

    return {
        "pass": output_pass,
        "fail": output_fail,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_assemble_join(
    head_file,
    tail_file,
    output_file,
    file_type="fastq",
    rc="tail",
    head_fields=None,
    tail_fields=None,
    gap=default_assembly_gap,
    coord_type=default_coord,
    delimiter=default_delimiter,
):
    """
    Concatenate ends with a gap (AssemblePairs.py join).
    No reference file.
    """
    output_pass, output_fail = assemble_output_paths(output_file)
    assemble_kwargs = {"gap": gap}

    pass_count = 0
    fail_count = 0

    prepared = _prepared_pairs(
        head_file, tail_file, file_type, rc, head_fields, tail_fields, delimiter,
        coord_type=coord_type,
    )

    with open(output_pass, "w") as pass_handle, open(output_fail, "w") as fail_handle:
        for head_record, tail_record, stitch_ann, stitch in _assembled(
            prepared, "join", None, assemble_kwargs, None, JOIN_CPUS
        ):
            if stitch.seq is not None and getattr(stitch, "valid", True):
                stitch.seq.id = flattenAnnotation(stitch_ann, delimiter=delimiter)
                stitch.seq.name = stitch.seq.id
                stitch.seq.description = ""
                SeqIO.write(stitch.seq, pass_handle, file_type)
                pass_count += 1
            else:
                SeqIO.write(head_record, fail_handle, file_type)
                SeqIO.write(tail_record, fail_handle, file_type)
                fail_count += 1

    return {
        "pass": output_pass,
        "fail": output_fail,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_assemble_reference(
    head_file,
    tail_file,
    output_file,
    ref_file,
    file_type="fastq",
    rc="tail",
    head_fields=None,
    tail_fields=None,
    min_ident=default_assembly_min_ident,
    evalue=default_assembly_evalue,
    max_hits=default_assembly_max_hits,
    fill=False,
    aligner=DEFAULT_REFERENCE_ALIGNER,
    coord_type=default_coord,
    delimiter=default_delimiter,
):
    """
    Reference-guided assembly (AssemblePairs.py reference).
    ref_file: uploaded reference FASTA file_id (required).
    """
    output_pass, output_fail = assemble_output_paths(output_file)
    ref_path = _resolve_ref_path(ref_file)
    ref_dict, ref_db, db_handle, aligner, aligner_exec = _open_reference_db(
        ref_path, aligner
    )

    # db_exec is only for building the DB — not passed to referenceAssembly
    assemble_kwargs = {
        "ref_dict": ref_dict,
        "ref_db": ref_db,
        "min_ident": min_ident,
        "evalue": evalue,
        "max_hits": max_hits,
        "fill": fill,
        "aligner": aligner,
        "aligner_exec": aligner_exec,
    }

    pass_count = 0
    fail_count = 0

    prepared = _prepared_pairs(
        head_file, tail_file, file_type, rc, head_fields, tail_fields, delimiter,
        coord_type=coord_type,
    )

    try:
        with open(output_pass, "w") as pass_handle, open(output_fail, "w") as fail_handle:
            for head_record, tail_record, stitch_ann, stitch in _assembled(
                prepared,
                "reference",
                ref_path,
                assemble_kwargs,
                None,
                EXTERNAL_TOOL_CPUS,
            ):
                if stitch.seq is not None and getattr(stitch, "valid", True):
                    stitch.seq.id = flattenAnnotation(stitch_ann, delimiter=delimiter)
                    stitch.seq.name = stitch.seq.id
                    stitch.seq.description = ""
                    SeqIO.write(stitch.seq, pass_handle, file_type)
                    pass_count += 1
                else:
                    SeqIO.write(head_record, fail_handle, file_type)
                    SeqIO.write(tail_record, fail_handle, file_type)
                    fail_count += 1
    finally:
        _close_db(db_handle)

    return {
        "pass": output_pass,
        "fail": output_fail,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_assemble_sequential(
    head_file,
    tail_file,
    output_file,
    ref_file,
    file_type="fastq",
    rc="tail",
    head_fields=None,
    tail_fields=None,
    alpha=default_assembly_alpha,
    max_error=default_assembly_max_error,
    min_len=default_assembly_min_len,
    max_len=default_assembly_max_len,
    scan_reverse=False,
    min_ident=default_assembly_min_ident,
    evalue=default_assembly_evalue,
    max_hits=default_assembly_max_hits,
    fill=False,
    aligner=DEFAULT_REFERENCE_ALIGNER,
    coord_type=default_coord,
    delimiter=default_delimiter,
):
    """
    De novo then reference fallback (AssemblePairs.py sequential).
    ref_file: uploaded reference FASTA file_id (required).
    """
    output_pass, output_fail = assemble_output_paths(output_file)
    ref_path = _resolve_ref_path(ref_file)
    ref_dict, ref_db, db_handle, aligner, aligner_exec = _open_reference_db(
        ref_path, aligner
    )

    # db_exec is only for building the DB — not passed to sequentialAssembly
    assemble_kwargs = {
        "alpha": alpha,
        "max_error": max_error,
        "min_len": min_len,
        "max_len": max_len,
        "scan_reverse": scan_reverse,
        "assembly_stats": AssemblyStats(max_len + 1),
        "ref_dict": ref_dict,
        "ref_db": ref_db,
        "min_ident": min_ident,
        "evalue": evalue,
        "max_hits": max_hits,
        "fill": fill,
        "aligner": aligner,
        "aligner_exec": aligner_exec,
    }

    pass_count = 0
    fail_count = 0

    prepared = _prepared_pairs(
        head_file, tail_file, file_type, rc, head_fields, tail_fields, delimiter,
        coord_type=coord_type,
    )

    try:
        with open(output_pass, "w") as pass_handle, open(output_fail, "w") as fail_handle:
            for head_record, tail_record, stitch_ann, stitch in _assembled(
                prepared,
                "sequential",
                ref_path,
                assemble_kwargs,
                max_len,
                EXTERNAL_TOOL_CPUS,
            ):
                if stitch.seq is not None and getattr(stitch, "valid", True):
                    stitch.seq.id = flattenAnnotation(stitch_ann, delimiter=delimiter)
                    stitch.seq.name = stitch.seq.id
                    stitch.seq.description = ""
                    SeqIO.write(stitch.seq, pass_handle, file_type)
                    pass_count += 1
                else:
                    SeqIO.write(head_record, fail_handle, file_type)
                    SeqIO.write(tail_record, fail_handle, file_type)
                    fail_count += 1
    finally:
        _close_db(db_handle)

    return {
        "pass": output_pass,
        "fail": output_fail,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }
