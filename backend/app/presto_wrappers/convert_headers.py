"""
Wrappers for pRESTO ConvertHeaders (one function per subcommand).

Synchronous re-implementation of ConvertHeaders.convertHeaders: the same
per-record conversion, but writing the failures to the ``{stem}_fail{suffix}``
sibling the step-download endpoint expects and returning pass/fail counts for
the step statistics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from Bio import SeqIO

from presto.Annotation import (
    convert454Header,
    convertGenbankHeader,
    convertGenericHeader,
    convertIlluminaHeader,
    convertIMGTHeader,
    convertMIGECHeader,
    convertSRAHeader,
    flattenAnnotation,
)
from presto.IO import getFileType, readSeqFile

from app.pipeline.presto_params import normalize_delimiter

# Conversion functions that also take the annotation delimiter.
_DELIMITED = (convertGenericHeader, convertGenbankHeader)


def _run_convert_headers(
    seq_file: str,
    out_file: str,
    convert_func,
    convert_args: dict | None = None,
    delimiter=None,
) -> dict[str, Any]:
    """Reheader every record with convert_func; unconvertible reads fail."""
    args = dict(convert_args or {})
    delim = normalize_delimiter(delimiter)
    if convert_func in _DELIMITED:
        args["delimiter"] = delim

    in_type = getFileType(seq_file)
    out_path = Path(out_file)
    fail_path = out_path.with_name(f"{out_path.stem}_fail{out_path.suffix}")

    pass_count = fail_count = 0
    with open(out_path, "w") as pass_handle, open(fail_path, "w") as fail_handle:
        for seq in readSeqFile(seq_file):
            header = convert_func(seq.description, **args)

            if header is None:
                fail_count += 1
                SeqIO.write(seq, fail_handle, in_type)
                continue

            seq.id = seq.name = flattenAnnotation(header, delim)
            seq.description = ""
            SeqIO.write(seq, pass_handle, in_type)
            pass_count += 1

    # Drop the fail file when nothing failed, so the UI never offers an empty
    # download.
    if fail_count == 0:
        try:
            fail_path.unlink()
        except OSError:
            pass

    return {
        "pass": str(out_path),
        "fail": str(fail_path) if fail_count else None,
        "pass_count": pass_count,
        "fail_count": fail_count,
    }


def run_convert_headers_generic(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """
    Converts sequence headers with an unknown annotation system
    (ConvertHeaders.py generic).
    """
    return _run_convert_headers(
        seq_file, out_file, convertGenericHeader, delimiter=delimiter
    )


def run_convert_headers_454(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """Converts Roche 454 sequence headers (ConvertHeaders.py 454)."""
    return _run_convert_headers(
        seq_file, out_file, convert454Header, delimiter=delimiter
    )


def run_convert_headers_genbank(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """
    Converts NCBI GenBank and RefSeq sequence headers
    (ConvertHeaders.py genbank).
    """
    return _run_convert_headers(
        seq_file, out_file, convertGenbankHeader, delimiter=delimiter
    )


def run_convert_headers_illumina(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """Converts Illumina sequence headers (ConvertHeaders.py illumina)."""
    return _run_convert_headers(
        seq_file, out_file, convertIlluminaHeader, delimiter=delimiter
    )


def run_convert_headers_imgt(
    seq_file: str,
    out_file: str,
    simple: bool = False,
    delimiter=None,
) -> dict[str, Any]:
    """
    Converts sequence headers output by IMGT/GENE-DB (ConvertHeaders.py imgt).
    simple: keep only the allele name in the converted header.
    """
    return _run_convert_headers(
        seq_file,
        out_file,
        convertIMGTHeader,
        convert_args={"simple": bool(simple)},
        delimiter=delimiter,
    )


def run_convert_headers_migec(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """Converts sequence headers output by MIGEC (ConvertHeaders.py migec)."""
    return _run_convert_headers(
        seq_file, out_file, convertMIGECHeader, delimiter=delimiter
    )


def run_convert_headers_sra(
    seq_file: str,
    out_file: str,
    delimiter=None,
) -> dict[str, Any]:
    """
    Converts NCBI SRA or EMBL-EBI ENA sequence headers (ConvertHeaders.py sra).
    """
    return _run_convert_headers(
        seq_file, out_file, convertSRAHeader, delimiter=delimiter
    )
