from pathlib import Path

from presto.Annotation import parseAnnotation
from presto.Defaults import default_delimiter
from presto.IO import readSeqFile

from app.pipeline.capabilities import (
    Capability,
    capability_for_annotation_field,
)


def format_from_suffix(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    if ext in (".fastq", ".fq"):
        return "fastq"
    if ext in (".fasta", ".fa", ".fas"):
        return "fasta"
    raise ValueError(
        f"Cannot infer format from extension '{ext}' for {file_path}"
    )


def detect_file_type(file_path: str) -> str:
    with open(file_path, encoding="utf-8", errors="replace") as f:
        first_line = f.readline()

    if first_line.startswith("@"):
        return "fastq"
    if first_line.startswith(">"):
        return "fasta"
    return "unknown"


def _capabilities_from_header_text(text: str) -> set[Capability]:
    """Fallback / supplement: scan raw header text for pRESTO field names."""
    caps: set[Capability] = set()
    upper = text.upper()

    if "+" in text and "@" in text:
        caps.add(Capability.QUALITY)

    markers = (
        "BARCODE",
        "UMI",
        "UID",
        "PRIMER",
        "CONSCOUNT",
        "DUPCOUNT",
        "CREGION",
        "PRCONS",
    )
    for marker in markers:
        if marker in upper:
            cap = capability_for_annotation_field(marker)
            if cap:
                caps.add(cap)

    if "CONSCOUNT" in upper or "DUPCOUNT" in upper:
        caps.add(Capability.GROUPED)
    if "DUPCOUNT" in upper:
        caps.add(Capability.COLLAPSED)

    return caps


#: pRESTO's parseAnnotation always returns this key first (the sequence ID);
#: it is never a domain annotation, so it never belongs in the field registry.
_ID_KEY = "ID"


def inspect_headers(
    file_path: str, max_records: int = 200
) -> tuple[set[Capability], set[str], bool]:
    """
    Infer lane capabilities AND concrete annotation field names from sequence
    headers. Reads up to max_records sequences from the uploaded file.

    Returns (capabilities, fields, fields_confident). `fields_confident` is
    True only once at least one record parsed as a genuine FIELD=VALUE
    annotation (pRESTO's parseAnnotation still returns something -- just an
    ID -- for an unannotated header, so an empty `fields` result on its own
    doesn't tell you whether the header format is simply unrecognized or
    genuinely field-less). Callers must not treat `fields` as exhaustive
    while this is False -- e.g. a raw vendor header before ConvertHeaders.*
    normalizes it looks identical to a deliberately bare one.
    """
    file_type = detect_file_type(file_path)
    caps: set[Capability] = set()
    fields: set[str] = set()
    confident = False

    if file_type == "fastq":
        caps.add(Capability.QUALITY)

    if file_type == "unknown":
        text = Path(file_path).read_text(encoding="utf-8", errors="replace")[:50000]
        return _capabilities_from_header_text(text), fields, confident

    try:
        seen_named_field = False
        for index, seq in enumerate(readSeqFile(file_path)):
            if index >= max_records:
                break

            header = seq.description or seq.id or ""
            ann = parseAnnotation(header, delimiter=default_delimiter)
            names = {
                str(key).strip().upper()
                for key in ann
                if str(key).strip().upper() != _ID_KEY
            }
            if names:
                seen_named_field = True
                fields |= names
            for name in names:
                cap = capability_for_annotation_field(name)
                if cap:
                    caps.add(cap)

            caps |= _capabilities_from_header_text(header)

        confident = seen_named_field

    except Exception:
        with open(file_path, encoding="utf-8", errors="replace") as handle:
            sample = "".join(handle.readline() for _ in range(min(max_records * 4, 400)))
        caps |= _capabilities_from_header_text(sample)

    return caps, fields, confident


def detect_capabilities(file_path: str, max_records: int = 200) -> set[Capability]:
    """
    Infer lane capabilities from sequence headers (pRESTO annotations).
    Reads up to max_records sequences from the uploaded file.
    """
    caps, _fields, _confident = inspect_headers(file_path, max_records)
    return caps


def detect_fields(file_path: str, max_records: int = 200) -> tuple[set[str], bool]:
    """Concrete annotation field names seen in the file; see inspect_headers."""
    _caps, fields, confident = inspect_headers(file_path, max_records)
    return fields, confident
