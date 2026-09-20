from pathlib import Path

from presto.IO import readPrimerFile
from app.pipeline.presto_params import normalize_delimiter
from presto.Sequence import (
    compilePrimers,
    reverseComplement,
    getDNAScoreDict,
)

from app.core.file_store import get_file
from app.presto_wrappers.helper import _process_sequences
from app.presto_tools.mask_primers import (
    _align_primers_worker,
    _extract_primers_worker,
    _score_primers_worker,
)


def mask_primers_output_paths(out_file: str) -> tuple[str, str]:
    """
    Pass sequences go to out_file (pipeline step output path).
    Failed sequences go to a sibling *_fail* file.
    """
    path = Path(out_file)
    output_fail = path.with_name(f"{path.stem}_fail{path.suffix}")
    return str(path), str(output_fail)


def _build_process_args(**kwargs) -> dict:
    args = dict(kwargs)
    args["delimiter"] = normalize_delimiter(args.pop("delimiter", None))
    return args


def run_mask_primers_align(
    seq_file,
    primer_file,
    out_file,
    file_type=None,
    max_error=0.2,
    max_len=50,
    rev_primer=False,
    skip_rc=False,
    gap_penalty=(1, 1),
    mode="mask",
    barcode=False,
    barcode_length=None,
    barcode_field="BARCODE",
    primer_field="PRIMER",
    delimiter=None,
):
    primers = readPrimerFile(get_file(primer_file).path)
    output_pass, output_fail = mask_primers_output_paths(out_file)

    if rev_primer:
        primers = {k: reverseComplement(v) for k, v in primers.items()}

    primers_regex = compilePrimers(primers)
    score_dict = getDNAScoreDict(mask_score=(0, 1), gap_score=(0, 0))

    return _process_sequences(
        seq_file=seq_file,
        output_pass=output_pass,
        output_fail=output_fail,
        process_func=_align_primers_worker,
        process_args=_build_process_args(
            primers=primers,
            primers_regex=primers_regex,
            max_error=max_error,
            max_len=max_len,
            rev_primer=rev_primer,
            skip_rc=skip_rc,
            mode=mode,
            barcode=barcode,
            barcode_length=barcode_length,
            barcode_field=barcode_field,
            primer_field=primer_field,
            gap_penalty=gap_penalty,
            score_dict=score_dict,
            delimiter=delimiter,
        ),
        file_type=file_type,
    )


def run_mask_primers_score(
    seq_file,
    primer_file,
    out_file,
    file_type=None,
    start=0,
    max_error=0.2,
    rev_primer=False,
    mode="mask",
    barcode=False,
    barcode_length=None,
    barcode_field="BARCODE",
    primer_field="PRIMER",
    delimiter=None,
):
    primers = readPrimerFile(get_file(primer_file).path)
    output_pass, output_fail = mask_primers_output_paths(out_file)

    if rev_primer:
        primers = {k: reverseComplement(v) for k, v in primers.items()}

    score_dict = getDNAScoreDict(mask_score=(0, 1), gap_score=(0, 0))

    return _process_sequences(
        seq_file=seq_file,
        output_pass=output_pass,
        output_fail=output_fail,
        process_func=_score_primers_worker,
        process_args=_build_process_args(
            primers=primers,
            max_error=max_error,
            start=start,
            rev_primer=rev_primer,
            mode=mode,
            barcode=barcode,
            barcode_length=barcode_length,
            barcode_field=barcode_field,
            primer_field=primer_field,
            score_dict=score_dict,
            delimiter=delimiter,
        ),
        file_type=file_type,
    )


def run_mask_primers_extract(
    seq_file,
    out_file,
    length,
    start=0,
    file_type=None,
    rev_primer=False,
    mode="mask",
    barcode=False,
    barcode_length=None,
    barcode_field="BARCODE",
    primer_field="PRIMER",
    delimiter=None,
):
    output_pass, output_fail = mask_primers_output_paths(out_file)

    return _process_sequences(
        seq_file=seq_file,
        output_pass=output_pass,
        output_fail=output_fail,
        process_func=_extract_primers_worker,
        process_args=_build_process_args(
            start=start,
            length=length,
            rev_primer=rev_primer,
            mode=mode,
            barcode=barcode,
            barcode_length=barcode_length,
            barcode_field=barcode_field,
            primer_field=primer_field,
            delimiter=delimiter,
        ),
        file_type=file_type,
    )
