"""
Wrappers for pRESTO ParseHeaders (one function per subcommand).
"""

import csv
from collections import OrderedDict
from time import time

from Bio import SeqIO

from presto.Annotation import (
    addHeader,
    collapseHeader,
    copyHeader,
    deleteHeader,
    expandHeader,
    flattenAnnotation,
    mergeHeader,
    parseAnnotation,
    renameHeader,
)
from presto.Defaults import default_delimiter, default_separator
from presto.IO import countSeqFile, getFileType, printProgress, readSeqFile


#: Column holding the sequence identifier in a ParseHeaders table. pRESTO's
#: parseAnnotation always returns it as the first key, so asking for it by name
#: is enough to get it into the TSV.
SEQUENCE_ID_FIELD = "ID"


def _as_list(value):
    """
    Coerce a single pRESTO list-parameter into an actual list.

    pRESTO takes `fields`, `values`, `names` and `actions` as parallel lists
    and pairs them with zip(). A bare string is itself iterable, so a value of
    "parsa" would zip character-by-character and store LENGTH=p -- the whole
    value silently truncated to its first letter. Wrapping a scalar keeps one
    value one value, whatever shape the request arrived in.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _upper_fields(fields):
    fields = _as_list(fields)
    if fields is None:
        return None
    return [str(f).upper() for f in fields]


def _run_modify_headers(
    seq_file: str,
    out_file: str,
    modify_func,
    fields,
    delimiter=default_delimiter,
    **modify_kwargs,
) -> str:
    """Reheader sequences (pRESTO modifyHeaders)."""
    fields = _upper_fields(fields)
    modify_args = {"fields": fields, **modify_kwargs}

    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    result_count = countSeqFile(seq_file)

    with open(out_file, "w") as out_handle:
        start_time = time()
        seq_count = 0
        for seq in seq_iter:
            printProgress(seq_count, result_count, 0.05, start_time=start_time)
            seq_count += 1

            header = parseAnnotation(seq.description, delimiter=delimiter)
            header = modify_func(header, delimiter=delimiter, **modify_args)

            seq.id = seq.name = flattenAnnotation(header, delimiter=delimiter)
            seq.description = ""
            SeqIO.write(seq, out_handle, in_type)

        printProgress(seq_count, result_count, 0.05, start_time=start_time)

    return out_file


def run_parse_headers_add(
    seq_file: str,
    out_file: str,
    fields,
    values,
    delimiter=default_delimiter,
):
    """
    Adds field/value pairs to header annotations (ParseHeaders.py add).
    fields and values are paired positionally and must have the same length.
    """
    values = _as_list(values)
    fields = _upper_fields(fields)
    if values is not None and fields is not None and len(fields) != len(values):
        raise ValueError(
            f"ParseHeaders.add needs one value per field: got {len(fields)} "
            f"field(s) and {len(values)} value(s)"
        )
    return _run_modify_headers(
        seq_file,
        out_file,
        addHeader,
        fields=fields,
        values=[str(v) for v in (values or [])],
        delimiter=delimiter,
    )


def run_parse_headers_collapse(
    seq_file: str,
    out_file: str,
    fields,
    actions,
    delimiter=default_delimiter,
):
    """
    Collapses duplicate annotation entries (ParseHeaders.py collapse).
    actions: min, max, sum, first, last, set, cat (one per field).
    """
    fields_list = _as_list(fields) or []
    actions = [str(a).lower() for a in _as_list(actions) or []]
    # presto.Annotation.collapseHeader pairs fields/actions with a bare zip(),
    # which silently truncates to the shorter list instead of erroring -- the
    # real ParseHeaders CLI catches this mismatch itself (parser.error) before
    # it ever reaches that function.
    if len(fields_list) != len(actions):
        raise ValueError(
            "ParseHeaders.collapse needs exactly one action per field: got "
            f"{len(fields_list)} field(s) and {len(actions)} action(s)"
        )
    return _run_modify_headers(
        seq_file,
        out_file,
        collapseHeader,
        fields=fields,
        actions=actions,
        delimiter=delimiter,
    )


def run_parse_headers_copy(
    seq_file: str,
    out_file: str,
    fields,
    names,
    actions=None,
    delimiter=default_delimiter,
):
    """
    Copies annotation fields to new names (ParseHeaders.py copy).
    """
    fields_list = _as_list(fields) or []
    names = _upper_fields(names) or []
    if len(fields_list) != len(names):
        raise ValueError(
            "ParseHeaders.copy needs exactly one new name per field: got "
            f"{len(fields_list)} field(s) and {len(names)} name(s)"
        )
    if actions is not None:
        actions = [str(a).lower() for a in _as_list(actions)]
        if len(actions) != len(names):
            raise ValueError(
                "ParseHeaders.copy needs exactly one action per new name: got "
                f"{len(actions)} action(s) and {len(names)} name(s)"
            )
    return _run_modify_headers(
        seq_file,
        out_file,
        copyHeader,
        fields=fields,
        names=names,
        actions=actions,
        delimiter=delimiter,
    )


def run_parse_headers_delete(
    seq_file: str,
    out_file: str,
    fields,
    delimiter=default_delimiter,
):
    """Deletes fields from header annotations (ParseHeaders.py delete)."""
    return _run_modify_headers(
        seq_file,
        out_file,
        deleteHeader,
        fields=fields,
        delimiter=delimiter,
    )


def run_parse_headers_expand(
    seq_file: str,
    out_file: str,
    fields,
    separator=default_separator,
    delimiter=default_delimiter,
):
    """
    Expands fields with multiple comma-separated values (ParseHeaders.py expand).
    """
    return _run_modify_headers(
        seq_file,
        out_file,
        expandHeader,
        fields=fields,
        separator=separator,
        delimiter=delimiter,
    )


def run_parse_headers_merge(
    seq_file: str,
    out_file: str,
    fields,
    name: str,
    action=None,
    delete=False,
    delimiter=default_delimiter,
):
    """
    Merges multiple fields into one (ParseHeaders.py merge).
    """
    if action is not None:
        action = str(action).lower()
    return _run_modify_headers(
        seq_file,
        out_file,
        mergeHeader,
        fields=fields,
        name=str(name).upper(),
        action=action,
        delete=delete,
        delimiter=delimiter,
    )


def run_parse_headers_rename(
    seq_file: str,
    out_file: str,
    fields,
    names,
    actions=None,
    delimiter=default_delimiter,
):
    """
    Renames annotation fields (ParseHeaders.py rename).
    """
    fields_list = _as_list(fields) or []
    names = _upper_fields(names) or []
    if len(fields_list) != len(names):
        raise ValueError(
            "ParseHeaders.rename needs exactly one new name per field: got "
            f"{len(fields_list)} field(s) and {len(names)} name(s)"
        )
    if actions is not None:
        actions = [str(a).lower() for a in _as_list(actions)]
        if len(actions) != len(names):
            raise ValueError(
                "ParseHeaders.rename needs exactly one action per new name: got "
                f"{len(actions)} action(s) and {len(names)} name(s)"
            )
    return _run_modify_headers(
        seq_file,
        out_file,
        renameHeader,
        fields=fields,
        names=names,
        actions=actions,
        delimiter=delimiter,
    )


def run_parse_headers_table(
    seq_file: str,
    out_file: str,
    fields,
    delimiter=default_delimiter,
):
    """
    Writes selected annotations to a tab-delimited table (ParseHeaders.py table).

    The sequence ID is always the first column, whether or not the user asked
    for it: a row of annotations that cannot be traced back to the read it came
    from is not much use, and it is the column anyone joining this table
    against the sequence files needs.

    This step writes a TSV rather than reads, so it ends the sequence stream
    and has no pass/fail split -- the table itself is the whole output.
    """
    fields = _upper_fields(fields) or []
    # Put ID first and drop any duplicate the user listed themselves.
    columns = [SEQUENCE_ID_FIELD] + [f for f in fields if f != SEQUENCE_ID_FIELD]

    seq_iter = readSeqFile(seq_file)
    result_count = countSeqFile(seq_file)

    with open(out_file, "w", newline="") as out_handle:
        writer = csv.DictWriter(
            out_handle,
            extrasaction="ignore",
            restval="",
            delimiter="\t",
            fieldnames=columns,
        )
        writer.writeheader()

        start_time = time()
        seq_count = 0
        rows_written = 0
        for seq in seq_iter:
            printProgress(seq_count, result_count, 0.05, start_time=start_time)
            seq_count += 1
            ann = parseAnnotation(seq.description, columns, delimiter=delimiter)
            if ann:
                writer.writerow(ann)
                rows_written += 1

        printProgress(seq_count, result_count, 0.05, start_time=start_time)

    return {
        "primary": out_file,
        "outputs": [out_file],
        # Reported so the step's stats show rows, not a sequence count guessed
        # from the file's line count.
        "table_rows": rows_written,
        "input_count": seq_count,
    }
