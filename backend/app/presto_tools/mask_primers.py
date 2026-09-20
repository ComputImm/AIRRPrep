from presto.Defaults import default_delimiter
from presto.Multiprocessing import SeqResult
from presto.Sequence import (
    extractAlignment,
    localAlignment,
    maskSeq,
    scoreAlignment,
)


def _align_primers_worker(
    data,
    primers,
    primers_regex,
    max_error,
    max_len,
    rev_primer,
    skip_rc,
    mode,
    barcode,
    barcode_length,
    barcode_field,
    primer_field,
    gap_penalty,
    score_dict,
    delimiter=default_delimiter,
):
    result = SeqResult(data.id, data.data)

    align = localAlignment(
        data.data,
        primers,
        primers_regex=primers_regex,
        max_error=max_error,
        max_len=max_len,
        rev_primer=rev_primer,
        skip_rc=skip_rc,
        gap_penalty=gap_penalty,
        score_dict=score_dict,
    )

    if not align:
        result.valid = False
        return result

    out_seq = maskSeq(
        align,
        mode=mode,
        barcode=barcode,
        barcode_length=barcode_length,
        barcode_field=barcode_field,
        primer_field=primer_field,
        delimiter=delimiter,
    )

    result.results = out_seq
    # A primer covering the whole read leaves a zero-length masked/cut
    # sequence; real pRESTO treats that as a failed read rather than passing
    # an empty record through (venv/Scripts/MaskPrimers.py:127).
    result.valid = bool(align.error <= max_error) if len(out_seq) > 0 else False

    return result


def _score_primers_worker(
    data,
    primers,
    max_error,
    start,
    rev_primer,
    mode,
    barcode,
    barcode_length,
    barcode_field,
    primer_field,
    score_dict,
    delimiter=default_delimiter,
):
    result = SeqResult(data.id, data.data)

    align = scoreAlignment(
        data.data,
        primers,
        start=start,
        rev_primer=rev_primer,
        score_dict=score_dict,
    )

    if not align:
        result.valid = False
        return result

    out_seq = maskSeq(
        align,
        mode=mode,
        barcode=barcode,
        barcode_length=barcode_length,
        barcode_field=barcode_field,
        primer_field=primer_field,
        delimiter=delimiter,
    )

    result.results = out_seq
    result.valid = bool(align.error <= max_error) if len(out_seq) > 0 else False

    return result


def _extract_primers_worker(
    data,
    start,
    length,
    rev_primer,
    mode,
    barcode,
    barcode_length,
    barcode_field,
    primer_field,
    delimiter=default_delimiter,
):
    result = SeqResult(data.id, data.data)

    align = extractAlignment(
        data.data,
        start=start,
        length=length,
        rev_primer=rev_primer,
    )

    if not align:
        result.valid = False
        return result

    out_seq = maskSeq(
        align,
        mode=mode,
        barcode=barcode,
        barcode_length=barcode_length,
        barcode_field=barcode_field,
        primer_field=primer_field,
        delimiter=delimiter,
    )

    result.results = out_seq
    result.valid = True

    return result
