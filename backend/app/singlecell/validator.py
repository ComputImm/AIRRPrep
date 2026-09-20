# app/singlecell/validator.py
"""
Annotation-leakage stripping and final record validation.

strip_leakage_fields() is applied twice in the pipeline: once by each adapter
right after reading a raw row (defense at the source), and once more here,
right before FASTA/TSV generation (defense at the sink) — so a future adapter
bug can never leak an annotation field through to the output IMGT consumes.
"""

import re

from app.singlecell.errors import SingleCellValidationError
from app.singlecell.models import UnifiedRecord

# Matches AIRR-style leakage fields (v_call, junction_aa, v_identity, ...) AND
# Cell Ranger's own column names for the same concepts (v_gene, cdr3, cdr3_nt)
# — without the gene/cdr3 aliases, the literal "v_call"/"junction" strings
# would never appear in a Cell Ranger CSV and this rule would be silently
# defeated for that input format.
_LEAKAGE_PATTERNS = [
    re.compile(r".*_call$", re.IGNORECASE),
    re.compile(r".*_identity$", re.IGNORECASE),
    re.compile(r".*_alignment$", re.IGNORECASE),
    re.compile(r".*_cigar$", re.IGNORECASE),
    re.compile(r"^v_gene$", re.IGNORECASE),
    re.compile(r"^d_gene$", re.IGNORECASE),
    re.compile(r"^j_gene$", re.IGNORECASE),
    re.compile(r"^c_gene$", re.IGNORECASE),
    re.compile(r"^junction(_aa)?$", re.IGNORECASE),
    re.compile(r"^cdr3(_nt|_aa)?$", re.IGNORECASE),
    # The remaining names the spec lists explicitly (single_cell.md's
    # CR_ANNOTATION_COLS / CR_AIRR_ANNOTATION_COLS). Framework and CDR
    # regions are annotation-derived exactly like the calls are, and `chain`
    # is Cell Ranger's locus assignment — all of them are IMGT's job.
    re.compile(r"^fwr[1-4](_aa)?$", re.IGNORECASE),
    re.compile(r"^cdr[12](_nt|_aa)?$", re.IGNORECASE),
    re.compile(r"^chain$", re.IGNORECASE),
    re.compile(r"^rev_comp$", re.IGNORECASE),
    re.compile(r"^productive$", re.IGNORECASE),
]


def is_leakage_field(field_name: str) -> bool:
    return any(pattern.match(field_name) for pattern in _LEAKAGE_PATTERNS)


def strip_leakage_fields(row: dict) -> dict:
    """Drop any key that is an annotation-derived (leakage) field."""
    return {k: v for k, v in row.items() if not is_leakage_field(k)}


_VALID_BASES = set("ACGTUNRYSWKMBDHVacgtunryswkmbdhv-")


def validate_records(
    records: list[UnifiedRecord],
) -> tuple[list[UnifiedRecord], list[str]]:
    """
    Drop records with empty/invalid sequences or duplicate sequence_ids.
    Returns (valid_records, warnings). Raises SingleCellValidationError if
    nothing survives.
    """
    warnings: list[str] = []
    seen_ids: set[str] = set()
    valid: list[UnifiedRecord] = []

    for record in records:
        if not record.sequence or any(c not in _VALID_BASES for c in record.sequence):
            warnings.append(
                f"Dropped {record.sequence_id!r}: empty or invalid sequence"
            )
            continue
        if record.sequence_id in seen_ids:
            warnings.append(f"Dropped duplicate sequence_id {record.sequence_id!r}")
            continue
        seen_ids.add(record.sequence_id)
        valid.append(record)

    if not valid:
        raise SingleCellValidationError(
            "No valid sequences remained after validation"
        )

    return valid, warnings
